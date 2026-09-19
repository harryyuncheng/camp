import ActivityKit
import Foundation

struct LunchAttributes: ActivityAttributes {
    typealias ContentState = LunchSession
    let sessionID: UUID

    var url: URL { URL(string: "lunchline://lunch/\(sessionID.uuidString)")! }
}
