import SwiftUI
import BatonKit

/// Engine-owned wording for an empty surface, paired without inventing display copy.
public struct EmptyStateContent: Equatable, Sendable {
    public let title: Note
    public let body: Note
    /// Pairs the catalogue title with its explanatory body.
    public init(title: Note, body: Note) { self.title = title; self.body = body }
    /// Finds the matching title and body notes for one presentation state.
    public static func find(_ prefix: String, in notes: [Note]) -> Self? {
        guard let title = notes.first(where: { $0.id == prefix + ".title" }),
              let body = notes.first(where: { $0.id == prefix + ".body" }) else { return nil }
        return Self(title: title, body: body)
    }
}

/// A calm branded explanation, with an optional existing navigation action.
public struct EmptyStateView: View {
    @Environment(\.batonTheme) private var theme
    private let content: EmptyStateContent
    private let compact: Bool
    private let actionLabel: Note?
    private let action: (() -> Void)?

    /// Displays existing wording and, when supplied, an existing navigation action.
    public init(content: EmptyStateContent, compact: Bool = false,
                actionLabel: Note? = nil, action: (() -> Void)? = nil) {
        self.content = content; self.compact = compact
        self.actionLabel = actionLabel; self.action = action
    }

    public var body: some View {
        VStack(spacing: compact ? 12 : 18) {
            BrandMark(size: compact ? 58 : 92).accessibilityHidden(true)
            VStack(spacing: 8) {
                Text(content.title.text)
                    .font(compact ? .callout.weight(.semibold) : .title3.weight(.semibold))
                    .foregroundStyle(theme.text)
                Text(content.body.text)
                    .font(compact ? .caption : .callout)
                    .foregroundStyle(theme.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let actionLabel, let action {
                Button(actionLabel.text, action: action)
                    .buttonStyle(BatonButtonStyle(meaning: .action, compact: compact))
            }
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: compact ? 300 : 400)
        .padding(compact ? 14 : 28)
        .frame(maxWidth: .infinity, minHeight: compact ? 190 : 320)
        .accessibilityElement(children: .contain)
    }
}
