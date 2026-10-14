import Foundation
import Combine
import BatonKit

/// Keeps generation consent, answer review and addition consent independent.
@MainActor public final class SecondOpinionViewModel: ObservableObject {
    @Published public private(set) var response: OpinionResponse?
    @Published public private(set) var answer: AskResult?
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var busy = false
    @Published public private(set) var question = ""
    @Published public private(set) var turn: Turn?
    private let engine: any EngineClient
    private var source = ""
    private var writer = ""
    private var revision = 0
    private var gate = ConfirmationGate()
    private var answerReceipt: PlanDisplayReceipt?
    private var automaticReviewedAnswers: Set<String> = []
    private var presentationNotes: [Note] = []
    public func label(_ id: String) -> Note? { (notes + presentationNotes).first { $0.id == id } }
    public var answerActions: [NoteButton] { label("ask.actions")?.buttons ?? [] }
    private var runCancellation: NoteButton?
    public var running: Bool { ["pending", "running"].contains(response?.state ?? "") }
    private var attempted: Set<String> = []
    public init(engine: any EngineClient) {
        self.engine = engine; presentationNotes = SetupPresentation.opinionLabels
        question = label("ask.default_question")?.text ?? ""
    }
    public var emptyNote: Note? { SetupPresentation.chooseChat }
    public var notes: [Note] { response?.plan.map(displayedPlanNotes) ?? response?.notes ?? [] }
    public var displayReceipt: PlanDisplayReceipt {
        PlanDisplayReceipt(planID: response?.plan?.planID ?? response?.requestID ?? "opinion", revision: revision, notes: notes)
    }
    public var answerDisplayReceipt: PlanDisplayReceipt? {
        guard let answer, let id = answer.answerID, !answer.answer.isEmpty else { return nil }
        // The exact answer text belongs to the display identity, never to a new app sentence.
        return PlanDisplayReceipt(planID: id + ":" + answer.answer, revision: revision, notes: answer.notes)
    }
    public var buttons: [NoteButton] {
        if running { return runCancellation.map { [$0] } ?? [] }
        guard let plan = response?.plan,
              ["ask.preview", "ask.add_preview", "ask.attach_preview"].contains(plan.confirmation?.id ?? "") else { return [] }
        return plan.confirmation?.buttons ?? []
    }
    public var canConfirm: Bool {
        guard let response, let plan = response.plan, !busy, !plan.applied, !plan.decisionNeeded,
              !plan.planID.isEmpty, !attempted.contains(plan.planID), buttons.contains(where: { $0.id == "confirm" }),
              gate.permits(notes, identity: displayReceipt.identity) else { return false }
        if response.stage == "generate" { return response.readOnly == true && answer == nil && plan.steps.isEmpty }
        guard response.stage == "add", let answer, let id = answer.answerID, !id.isEmpty,
              let receipt = answerDisplayReceipt, answerReceipt == receipt,
              plan.steps.count == 1, let step = plan.steps.first,
              step.tool == source.split(separator: ":").first.map(String.init),
              ["add", "attach"].contains(step.action) else { return false }
        return response.answerID == id && response.answerText == answer.answer
    }
    public func chooseAnswerAction(_ button: NoteButton, copy: (String) -> Void = { _ in }) async {
        guard answerActions.contains(button), !busy, !running, let answer else { return }
        switch button.id {
        case "copy": copy(answer.answer)
        case "ask_again": await askAgain(question: question)
        case "discard": discard()
        case "retry": await reviewAddition()
        default: break
        }
    }
    public var canReviewAddition: Bool { !busy && answerDisplayReceipt != nil && answerReceipt == answerDisplayReceipt }
    public func didDisplay(_ receipt: PlanDisplayReceipt) {
        guard receipt == displayReceipt else { return }
        objectWillChange.send(); gate.markDisplayed(notes, identity: receipt.identity)
    }
    public func didDisplayAnswer(_ receipt: PlanDisplayReceipt) {
        guard receipt == answerDisplayReceipt else { return }
        objectWillChange.send(); answerReceipt = receipt
    }
    public func preview(from: String, turn: Turn? = nil, tool: String, question: String) async {
        guard !busy else { return }
        revision += 1; response = nil; answer = nil; answerReceipt = nil; gate = ConfirmationGate(); errorNote = nil
        runCancellation = nil
        let question = question.isEmpty ? label("ask.default_question")?.text ?? "" : question
        source = from; writer = tool; self.turn = turn; self.question = question
        var arguments = ["--chat", from, "--tool", tool, "--question", question, "--dry-run", "--background"]
        if let turn { arguments += ["--turn", String(turn.id)] }
        await request("ask", arguments)
    }
    private func request(_ command: String, _ arguments: [String]) async {
        guard let transport = engine as? any EngineTransport else { return }
        busy = true; defer { busy = false }
        do {
            let result = try await transport.response(command: command, arguments: arguments, as: OpinionResponse.self)
            response = result; errorNote = result.error?.note
            for note in result.notes {
                presentationNotes.removeAll { $0.id == note.id && $0.values["key"] == note.values["key"] }
                presentationNotes.append(note)
            }
            if result.stage == "generate", result.plan?.confirmation?.id == "ask.preview" {
                runCancellation = result.plan?.confirmation?.buttons.first { $0.id == "cancel" }
            }
            if result.state == "completed", let value = result.answer, !(value.answerID ?? "").isEmpty {
                answer = value; answerReceipt = nil
            }
            if ["cancelled", "deadline"].contains(result.state ?? "") { answer = nil; answerReceipt = nil }
        } catch let error as EngineCommandError { errorNote = error.note ?? SetupPresentation.failure }
        catch { errorNote = SetupPresentation.failure }
    }
    public func confirm() async {
        guard canConfirm, let plan = response?.plan else { return }
        attempted.insert(plan.planID)
        let command = response?.stage == "add" ? "ask-add" : "ask"
        await request(command, (command == "ask-add" ? ["add"] : []) + ["--confirm", plan.planID])
        revision += 1; gate = ConfirmationGate(); answerReceipt = nil
    }
    public func poll() async {
        guard !busy, let id = response?.requestID, ["pending", "running"].contains(response?.state ?? "") else { return }
        await request("ask", ["--status", id])
        revision += 1; gate = ConfirmationGate(); answerReceipt = nil
    }
    public func cancelRun() async {
        guard !busy, let id = response?.requestID, ["pending", "running"].contains(response?.state ?? "") else { return }
        await request("ask", ["--cancel", id]); revision += 1; gate = ConfirmationGate()
    }
    public func reviewAdditionAutomatically() async {
        guard canReviewAddition, let id = answer?.answerID, automaticReviewedAnswers.insert(id).inserted else { return }
        await reviewAddition()
    }
    public func reviewAddition() async {
        guard canReviewAddition, let id = answer?.answerID else { return }
        await request("ask-add", ["add", "--answer", id, "--dry-run"])
        revision += 1; gate = ConfirmationGate(); answerReceipt = nil
    }
    public func updateQuestion(_ value: String) {
        guard !busy, !running else { return }
        question = value
        if answer == nil { revision += 1; response = nil; answerReceipt = nil; gate = ConfirmationGate() }
    }
    public func askAgain(question: String) async { await preview(from: source, turn: turn, tool: writer, question: question) }
    public func discard() {
        guard !busy, !["pending", "running"].contains(response?.state ?? "") else { return }
        revision += 1; answer = nil; response = nil; answerReceipt = nil; gate = ConfirmationGate()
    }
}
