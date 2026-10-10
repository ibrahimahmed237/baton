import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

private enum D7Failure: Error { case unavailable, staleToken }

/// Contract provider with request-bound, single-use stage tokens; no native runtime is claimed.
private actor D7Engine: EngineTransport {
    private(set) var calls: [(command: String, arguments: [String])] = []
    private(set) var generationCount = 0
    private(set) var creationCount = 0
    private var previews: [String: (arguments: [String], stage: String, object: [String: Any])] = [:]
    private var nonce = 0
    private var failStatus = false
    private var wrongLink = false
    private var failSetup = false
    private var wrongDestination = false
    private var blockBrief = false
    private var malformed: String?
    private var blockedLink: Int?
    private var waiting: CheckedContinuation<Void, Never>?
    let state: String
    init(state: String) { self.state = state }
    func commands() -> [String] { calls.map(\.command) }
    func arguments(of command: String) -> [[String]] { calls.filter { $0.command == command }.map(\.arguments) }
    func counts() -> (Int, Int) { (generationCount, creationCount) }
    func configure(failStatus: Bool = false, wrongLink: Bool = false, blockedLink: Int? = nil, failSetup: Bool = false, wrongDestination: Bool = false, blockBrief: Bool = false, malformed: String? = nil) {
        self.malformed = malformed; self.blockBrief = blockBrief; self.failSetup = failSetup; self.wrongDestination = wrongDestination; self.failStatus = failStatus; self.wrongLink = wrongLink; self.blockedLink = blockedLink
    }
    func isWaiting() -> Bool { waiting != nil }
    func resume() { waiting?.resume(); waiting = nil; blockedLink = nil; blockBrief = false }
    private func fixture(_ command: String, _ name: String) throws -> [String: Any] {
        let url = ComponentTests.root.appendingPathComponent("Fixtures/\(command).\(name).json")
        guard let object = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any] else { throw D7Failure.unavailable }
        return object
    }
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        calls.append((command, arguments))
        if command == "setup", failSetup { throw D7Failure.unavailable }
        if command == "brief", blockBrief { await withCheckedContinuation { waiting = $0 } }
        if command == "status", arguments.contains(String(blockedLink ?? -1)) {
            await withCheckedContinuation { waiting = $0 }
        }
        if command == "status", failStatus { throw D7Failure.unavailable }
        var object: [String: Any]
        if command == "brief" {
            if let index = arguments.firstIndex(of: "--confirm") {
                let id = arguments[index + 1]
                let original = Array(arguments.prefix(index))
                guard let preview = previews.removeValue(forKey: id), preview.arguments == original else { throw D7Failure.staleToken }
                if preview.stage == "generate" {
                    generationCount += 1
                    object = try fixture("brief", state + "_generated")
                    nonce += 1; let fresh = "generated-\(nonce)"
                    object["plan_id"] = fresh
                    previews[fresh] = (original, "create", object)
                } else {
                    creationCount += 1; object = preview.object; object["applied"] = true
                }
            } else {
                let offline = arguments.contains("offline")
                object = try fixture("brief", offline ? "d7_offline" : state)
                nonce += 1; let id = "preview-\(nonce)"; object["plan_id"] = id
                let base = arguments.filter { $0 != "--dry-run" }
                previews[id] = (base, object["stage"] as? String ?? "", object)
            }
        } else {
            if arguments.contains("--confirm") { throw D7Failure.unavailable } // Continue runtime belongs to CP3.
            object = try fixture(command, command == "setup" ? "d7_labels" : state)
        }
        if command == "brief", let malformed {
            var brief = object["brief"] as! [String: Any]
            switch malformed {
            case "missing_artifact": brief["artifact_id"] = ""
            case "empty_text": brief["text"] = ""
            case "empty_create": object["steps"] = []
            case "offline_generate":
                object["stage"] = "generate"; brief["writer"] = "codex"
                brief["estimated_tokens"] = 1800; brief["candidate_estimates"] = [["writer": "codex", "tokens": 1800]]
            case "wrong_bound": brief["estimated_tokens"] = 1700
            case "missing_cost": object["notes"] = []
            case "empty_steps": object["steps"] = []
            default: break
            }
            object["brief"] = brief
        }
        if command == "brief", wrongDestination { object["steps"] = [["tool": "unrelated", "action": "create", "turns": [], "reason": "", "needs": [], "notes": []]] }
        if command == "status", wrongLink { object["link_id"] = 900 }
        return try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
    }
}

@Suite(.serialized)
struct HandOffTests {
    static let linkedStates = ["d7_limit_reset", "d7_limit_no_reset", "d7_context_size", "d7_no_size", "d7_brief_fallback"]
    static let orchard = Chat(tool: "claude", id: "sample-a", name: "Imaginary orchard", folder: "/Users/example/orchard",
                              updatedAt: "2026-10-09T09:30:00Z", linked: false, toolLabel: "Claude")
    @MainActor private func loaded(_ state: String, to: String? = nil) async throws -> (HandOffViewModel, D7Engine) {
        let engine = D7Engine(state: state)
        let model = HandOffViewModel(engine: engine)
        let hasOffer = FileManager.default.fileExists(atPath: ComponentTests.root.appendingPathComponent("Fixtures/notify.\(state).json").path)
        let offers = hasOffer ? try await D7Engine(state: state).notify(tool: "claude", chat: "sample-a").offers : []
        await model.load(link: 3, offers: offers, to: to)
        return (model, engine)
    }

    @MainActor @Test func v1LimitOfferNamesToolsResetAndOriginalDestination() async throws {
        let (model, engine) = try await loaded("d7_limit_reset", to: "claude")
        let offer = try #require(model.offer)
        #expect(offer.text.contains("Claude") && offer.text.contains("Codex"))
        #expect(offer.values["time"] == .string("2026-10-09 15:00"))
        #expect(model.side("claude")?.usage.limit?.resetsAt == "2026-10-09T15:00:00Z")
        #expect(model.target == "claude")
        model.choose(try #require(offer.buttons.first { $0.id == "continue" }))
        #expect(model.pendingReview == .continueIn(link: 3, tool: "codex"))
        let commands = await engine.commands()
        #expect(!commands.contains("continue") && !commands.contains("brief"))
        // Show the future contract honestly; this provider cannot perform CP3 opening.
        let review = PlanReviewViewModel(engine: engine)
        await review.load(try #require(model.pendingReview))
        review.didDisplay(try #require(review.displayReceipt))
        #expect(!review.canConfirm)
        await review.confirm()
        #expect(review.outcome == nil)
        let calls = await engine.arguments(of: "continue")
        #expect(calls.count == 1 && !calls[0].contains("--confirm"))
    }
    @MainActor @Test func v2DismissalKeepsResetStatusAndDisablesOldOffer() async throws {
        let (model, _) = try await loaded("d7_limit_reset")
        let offer = try #require(model.offer)
        model.choose(try #require(offer.buttons.first { $0.id == "not_now" }))
        #expect(!model.bannerVisible)
        model.choose(try #require(offer.buttons.first { $0.id == "continue" }))
        #expect(model.pendingReview == nil)
        #expect(model.notes(for: "claude").contains { $0.id == "limit.available_at" })
        #expect(model.side("claude")?.usage.limit?.resetsAt == "2026-10-09T15:00:00Z")
    }
    @MainActor @Test func dismissedEventStaysDismissedAcrossReloadAndNewEventCanOfferAgain() async throws {
        let (model, engine) = try await loaded("d7_limit_reset")
        var offer = try #require(model.offer); model.dismissOffer()
        await model.load(link: 3, offers: [offer]); #expect(!model.bannerVisible)
        offer.values["offer_key"] = .string("new-limit")
        await model.load(link: 3, offers: [offer]); #expect(model.bannerVisible)
        let commands = await engine.commands(); #expect(!commands.contains("brief"))
    }
    @MainActor @Test func v3UnlinkedOfferRetainsNamedDestinationForLinkDialog() async throws {
        let engine = D7Engine(state: "d7_unlinked")
        let model = HandOffViewModel(engine: engine)
        let offers = try await engine.notify(tool: "claude", chat: "sample-a").offers
        await model.load(unlinked: Self.orchard, offers: offers)
        let offer = try #require(model.offer)
        model.choose(NoteButton(id: "continue", label: "Continue in Codex"))
        #expect(model.pendingReview == nil && model.linkRequested == nil)
        model.choose(try #require(offer.buttons.first { $0.id == "link_and_continue" }))
        #expect(model.linkRequested == Self.orchard && model.linkDestinationTool == "codex")
        let commands = await engine.commands()
        #expect(!commands.contains("status") && !commands.contains("brief"))
    }
    @MainActor @Test func v4BriefCostPrecedesGenerationAndArtifactNeedsFreshReviewBeforeCreation() async throws {
        let (model, engine) = try await loaded("d7_limit_reset")
        #expect(model.brief == nil)
        model.selectMode(.brief); await model.previewChoice()
        #expect(model.brief?.plan.stage == "generate")
        let details = try #require(model.brief?.brief)
        let estimate = try #require(details.estimatedTokens)
        #expect(estimate > 0)
        #expect(details.candidateEstimates?.reduce(0) { $0 + $1.tokens } == estimate)
        #expect(model.writerNotes.contains { $0.id == "brief.skipped_limit" })
        #expect(model.writerNotes.contains { $0.id == "brief.cost" })
        let totalCost = try #require(model.writerNotes.first { $0.id == "brief.total_cost" })
        #expect(totalCost.values["tokens"] == .number(Double(estimate)))
        let pinnedTokens = try #require(details.pinnedTokens)
        #expect(pinnedTokens > 0)
        #expect(model.writerNotes.contains { $0.id == "brief.pinned_size" && $0.values["tokens"] == .number(Double(pinnedTokens)) })
        #expect(await engine.counts() == (0, 0))
        model.beginReview()
        let review = PlanReviewViewModel(engine: engine)
        await review.load(try #require(model.pendingReview))
        #expect(!review.canConfirm)
        await review.confirm(); #expect(await engine.counts() == (0, 0))
        let generationReceipt = try #require(review.displayReceipt)
        review.didDisplay(generationReceipt); await review.confirm()
        #expect(await engine.counts() == (1, 0))
        #expect(review.plan?.stage == "create" && review.outcome == nil)
        let generated: BriefResult = try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d7_limit_reset_generated")
            .response(command: "brief", arguments: [], as: BriefResult.self)
        #expect(review.reviewed?.brief?.text == generated.brief.text)
        #expect(review.reviewed?.brief?.artifactID == generated.brief.artifactID)
        #expect(!(generated.brief.text ?? "").isEmpty)
        #expect(review.planNotes.contains { $0.id == "brief.summary_receipt" })
        review.didDisplay(generationReceipt)
        #expect(!review.canConfirm)
        await review.confirm(); #expect(await engine.counts() == (1, 0))
        review.didDisplay(try #require(review.displayReceipt)); await review.confirm()
        #expect(review.outcome == .applied)
        #expect(await engine.counts() == (1, 1))
        await review.confirm(); #expect(await engine.counts() == (1, 1))
    }
    @MainActor @Test func v5BothSidesShowKnownFullnessAndRealSummaryRecommendation() async throws {
        let (model, _) = try await loaded("d7_context_size")
        #expect(model.percent(for: "claude") == 82 && model.percent(for: "codex") == 13)
        #expect(model.contextNote(for: "claude")?.text == "About 164,000 tokens in use, 82% of 200,000.")
        #expect(model.notes(for: "claude").contains { $0.id == "context.nearly_full" })
        #expect(model.statusNotes.contains { $0.id == "brief.large_chat" })
    }
    @MainActor @Test func v6UnknownContextSizeShowsTokensOnly() async throws {
        let (model, _) = try await loaded("d7_no_size")
        #expect(model.percent(for: "claude") == nil)
        #expect(model.contextNote(for: "claude")?.id == "context.in_use_no_size")
        #expect(model.contextNote(for: "claude")?.text == "About 164,000 tokens in use.")
        #expect(!model.notes(for: "claude").contains { $0.id == "context.nearly_full" })
    }
    @MainActor @Test func noResetOfferDoesNotInventAvailabilityTime() async throws {
        let (model, _) = try await loaded("d7_limit_no_reset")
        #expect(model.offer?.id == "limit.offer_linked_no_reset_behind")
        #expect(model.offer?.values["resets_at"] == nil)
        #expect(model.limitedTool == "opencode")
        #expect(!model.notes(for: "opencode").contains { $0.id == "limit.available_at" })
    }
    @MainActor @Test func fullModeNeverPreviewsABriefAndOfflineChoiceNeverGenerates() async throws {
        let (model, engine) = try await loaded("d7_context_size")
        await model.previewChoice(); model.beginReview()
        #expect(model.pendingReview == .continueIn(link: 3, tool: "codex"))
        #expect(!(await engine.commands()).contains("brief"))
        model.selectMode(.brief); model.selectWriter(.offline); await model.previewChoice()
        #expect(model.request == .brief(link: 3, to: "codex", writer: "offline"))
        #expect(model.brief?.brief?.writer == "offline" && model.brief?.plan.stage == "create")
        #expect(model.writerNotes.contains { $0.id == "brief.used_offline" })
        #expect(await engine.counts() == (0, 0))
        model.beginReview(); let review = PlanReviewViewModel(engine: engine)
        await review.load(try #require(model.pendingReview))
        review.didDisplay(try #require(review.displayReceipt)); await review.confirm()
        #expect(await engine.counts() == (0, 1))
    }
    @MainActor @Test func largeChatChoicePreviewsCostAndFullChoiceClearsIt() async throws {
        let (model, engine) = try await loaded("d7_context_size")
        let recommendation = try #require(model.statusNotes.first { $0.id == "brief.large_chat" })
        await model.chooseRecommendation(try #require(recommendation.buttons.first { $0.id == "write_brief" }))
        #expect(model.mode == .brief && model.brief?.plan.stage == "generate")
        #expect(await engine.counts() == (0, 0))
        await model.chooseRecommendation(try #require(recommendation.buttons.first { $0.id == "send_in_full" }))
        #expect(model.mode == .full && model.brief == nil)
    }
    @MainActor @Test func selectionChangesInvalidatePreviewAndOldReviewIntent() async throws {
        let (model, _) = try await loaded("d7_context_size")
        model.selectMode(.brief); await model.previewChoice(); model.beginReview()
        #expect(model.brief != nil && model.pendingReview != nil)
        model.selectWriter(.offline)
        #expect(model.brief == nil && model.pendingReview == nil)
        await model.previewChoice(); model.selectTarget("claude")
        #expect(model.brief == nil && model.request == .brief(link: 3, to: "claude", writer: "offline"))
        model.selectMode(.full)
        #expect(model.request == .continueIn(link: 3, tool: "claude"))
    }
    @MainActor @Test func failedReloadCannotReuseOldStatusOfferOrAction() async throws {
        let (model, engine) = try await loaded("d7_limit_reset")
        model.selectMode(.brief); await model.previewChoice(); model.beginReview()
        await engine.configure(failStatus: true)
        await model.load(link: 3)
        #expect(model.failed && !model.canAct && model.status == nil && model.offer == nil)
        #expect(model.target == nil && model.brief == nil && model.pendingReview == nil && model.chat == nil)
        #expect(model.mode == .full && model.writer == .automatic)
        model.beginReview(); #expect(model.pendingReview == nil)
        #expect(model.errorNote?.id == "plan.unavailable")
    }
    @MainActor @Test func mismatchedStatusOrDestinationNeverExposesActions() async throws {
        let engine = D7Engine(state: "d7_context_size"); let model = HandOffViewModel(engine: engine)
        await engine.configure(wrongLink: true); await model.load(link: 3)
        #expect(model.failed && model.request == nil)
        await engine.configure(); await model.load(link: 3, to: "unknown")
        #expect(model.failed && model.status == nil && model.request == nil)
    }
    @MainActor @Test func setupFailureHasABrandedErrorAffordanceAndNoOldActions() async throws {
        let (model, engine) = try await loaded("d7_limit_reset")
        await engine.configure(failSetup: true); await model.load(link: 3)
        #expect(model.hasUnwordedError && model.failed && !model.canAct)
        #expect(model.status == nil && model.offer == nil && model.request == nil)
    }
    @MainActor @Test func previewCannotExposeAnotherDestinationAsTheChosenBrief() async throws {
        let (model, engine) = try await loaded("d7_context_size")
        await engine.configure(wrongDestination: true); model.selectMode(.brief); await model.previewChoice()
        #expect(model.failed && model.brief == nil && model.request == nil)
    }
    @MainActor @Test func offlineChoiceRefusesPaidStagesAndIncompleteArtifacts() async throws {
        for malformed in ["missing_artifact", "empty_text", "empty_create", "offline_generate"] {
            let (model, engine) = try await loaded("d7_context_size")
            await engine.configure(malformed: malformed)
            model.selectMode(.brief); model.selectWriter(.offline); await model.previewChoice()
            #expect(model.failed && model.brief == nil && model.request == nil)
            #expect(await engine.counts() == (0, 0))
        }
    }
    @MainActor @Test func understatedGenerationBoundIsNotActionable() async throws {
        let (model, engine) = try await loaded("d7_context_size")
        await engine.configure(malformed: "wrong_bound"); model.selectMode(.brief); await model.previewChoice()
        #expect(model.failed && model.brief == nil && model.request == nil)
        #expect(await engine.counts() == (0, 0))
    }
    @MainActor @Test func directReviewCannotBypassBriefValidation() async throws {
        for malformed in ["missing_artifact", "empty_text", "empty_create", "offline_generate", "wrong_bound", "missing_cost", "empty_steps"] {
            let (model, engine) = try await loaded("d7_context_size")
            await engine.configure(malformed: malformed)
            model.selectMode(.brief)
            if !["wrong_bound", "missing_cost", "empty_steps"].contains(malformed) { model.selectWriter(.offline) }
            model.beginReview()
            let review = PlanReviewViewModel(engine: engine)
            await review.load(try #require(model.pendingReview))
            #expect(review.plan == nil && !review.canConfirm)
            await review.confirm(); #expect(await engine.counts() == (0, 0))
        }
    }
    @MainActor @Test func forgedOfferIdentityIsNotActionable() async throws {
        let engine = D7Engine(state: "d7_limit_reset"); let model = HandOffViewModel(engine: engine)
        var offer = try #require(try await engine.notify(tool: "claude", chat: "sample-a").offers.first)
        offer.values["destination_chat_id"] = .string("unrelated")
        await model.load(link: 3, offers: [offer])
        #expect(model.offer == nil && !model.bannerVisible)
        model.choose(try #require(offer.buttons.first))
        #expect(model.pendingReview == nil)
    }
    @MainActor @Test func outOfOrderReloadDoesNotReviveOldLink() async throws {
        let engine = D7Engine(state: "d7_context_size"); let model = HandOffViewModel(engine: engine)
        await engine.configure(blockedLink: 17)
        let old = Task { await model.load(link: 17) }
        while !(await engine.isWaiting()) { await Task.yield() }
        #expect(model.loading && model.status == nil && model.request == nil)
        await model.load(link: 3, to: "claude")
        #expect(model.linkID == 3 && model.target == "claude")
        await engine.resume(); await old.value
        #expect(model.linkID == 3 && model.target == "claude" && !model.failed)
    }
    @MainActor @Test func lateBriefResponseCannotReplaceFreshFullModeLoad() async throws {
        let (model, engine) = try await loaded("d7_context_size")
        model.selectMode(.brief); await engine.configure(blockBrief: true)
        let old = Task { await model.previewChoice() }
        while !(await engine.isWaiting()) { await Task.yield() }
        #expect(model.loading && model.request == nil)
        await model.load(link: 3, to: "claude")
        await engine.resume(); await old.value
        #expect(model.mode == .full && model.brief == nil && model.target == "claude")
        #expect(model.request == .continueIn(link: 3, tool: "claude"))
    }
    @MainActor @Test func everyRequiredStateRendersInBothThemes() async throws {
        let directory = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var models: [(String, HandOffViewModel)] = []
        for state in Self.linkedStates {
            let model = try await loaded(state).0; models.append((state + "-full", model))
            let brief = try await loaded(state).0; brief.selectMode(.brief); await brief.previewChoice()
            models.append((state + "-brief", brief))
        }
        let (offline, _) = try await loaded("d7_context_size"); offline.selectMode(.brief); offline.selectWriter(.offline); await offline.previewChoice()
        models.append(("d7_offline", offline))
        let (failed, failingEngine) = try await loaded("d7_context_size"); await failingEngine.configure(failStatus: true); await failed.load(link: 3)
        models.append(("d7_failed_reload", failed))
        let (setupFailed, setupEngine) = try await loaded("d7_context_size")
        await setupEngine.configure(failSetup: true); await setupFailed.load(link: 3)
        models.append(("d7_setup_failed", setupFailed))
        let engine = D7Engine(state: "d7_unlinked"); let unlinked = HandOffViewModel(engine: engine)
        await unlinked.load(unlinked: Self.orchard, offers: try await engine.notify(tool: "claude", chat: "sample-a").offers)
        models.append(("d7_unlinked", unlinked))
        for (name, model) in models { for theme in Theme.allCases {
            let renderer = ImageRenderer(content: HandOffView(model: model).environment(\.batonTheme, theme).environment(\.batonSnapshotPresentation, true))
            let image = try #require(renderer.nsImage)
            let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff))
            let png = try #require(bitmap.representation(using: .png, properties: [:]))
            #expect(!png.isEmpty); try png.write(to: directory.appendingPathComponent("D7-\(name.dropFirst(3))-\(theme.rawValue).png"))
        } }
        let loadingEngine = D7Engine(state: "d7_context_size"); let loading = HandOffViewModel(engine: loadingEngine)
        await loadingEngine.configure(blockedLink: 17)
        let loadingTask = Task { await loading.load(link: 17) }
        while !(await loadingEngine.isWaiting()) { await Task.yield() }
        for theme in Theme.allCases {
            let renderer = ImageRenderer(content: HandOffView(model: loading).environment(\.batonTheme, theme).environment(\.batonSnapshotPresentation, true))
            let image = try #require(renderer.nsImage); let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff)); let png = try #require(bitmap.representation(using: .png, properties: [:]))
            #expect(!png.isEmpty); try png.write(to: directory.appendingPathComponent("D7-loading-\(theme.rawValue).png"))
        }
        await loadingEngine.resume(); await loadingTask.value
        let reviewEngine = D7Engine(state: "d7_limit_reset"); let review = PlanReviewViewModel(engine: reviewEngine)
        await review.load(.brief(link: 3, to: "codex", writer: nil))
        #expect(review.plan?.stage == "generate" && review.reviewed?.brief?.text == "")
        for theme in Theme.allCases {
            let renderer = ImageRenderer(content: PlanReviewView(model: review).environment(\.batonTheme, theme).environment(\.batonSnapshotPresentation, true))
            let image = try #require(renderer.nsImage); let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff)); let png = try #require(bitmap.representation(using: .png, properties: [:]))
            #expect(!png.isEmpty); try png.write(to: directory.appendingPathComponent("D7-generation-cost-\(theme.rawValue).png"))
        }
        review.didDisplay(try #require(review.displayReceipt)); await review.confirm()
        #expect(review.plan?.stage == "create")
        for theme in Theme.allCases {
            let renderer = ImageRenderer(content: PlanReviewView(model: review).environment(\.batonTheme, theme).environment(\.batonSnapshotPresentation, true))
            let image = try #require(renderer.nsImage)
            let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff))
            let png = try #require(bitmap.representation(using: .png, properties: [:]))
            #expect(!png.isEmpty); try png.write(to: directory.appendingPathComponent("D7-generated-create-\(theme.rawValue).png"))
        }
    }
}
