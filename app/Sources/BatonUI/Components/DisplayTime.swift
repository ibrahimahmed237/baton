import Foundation
import BatonKit

/// System-local date presentation for timestamps supplied by the engine.
public enum DisplayTime {
    public static func noteText(_ text: String, values: [String: JSONValue]) -> String {
        var rendered = text
        for key in ["at", "since", "resets_at"] {
            if case .string(let timestamp) = values[key] { rendered = rendered.replacingOccurrences(of: timestamp, with: string(timestamp)) }
        }
        return rendered
    }
    public static func string(_ timestamp: String, now: Date = Date(), locale: Locale = .current,
                              calendar: Calendar = .current, timeZone: TimeZone = .current) -> String {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = parser.date(from: timestamp) ?? ISO8601DateFormatter().date(from: timestamp) else { return timestamp }
        var localCalendar = calendar
        localCalendar.timeZone = timeZone
        let formatter = DateFormatter()
        formatter.locale = locale; formatter.calendar = localCalendar; formatter.timeZone = timeZone
        formatter.dateStyle = localCalendar.isDate(date, inSameDayAs: now) ? .none : .short
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}
