import ActivityKit
import Foundation

struct LunchAttributes: ActivityAttributes {
    typealias ContentState = LunchSession
    let sessionID: UUID
    var group: DemoLunchGroup? = nil

    var url: URL { URL(string: "camp://lunch/\(sessionID.uuidString)")! }
}
