import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

/// Connections card for the Python recommender. Connect checks `/v1/health`; "Request lunch offer"
/// builds a MealContext from the saved configuration and shows the result on the lunch card.
struct CampRecommendationView: View {
    @ObservedObject var store: CampSettingsStore
    var body: some View {
        CampCard("Recommendation service", subtitle: "The deterministic recommender: hard filters → scoring → office batching. Jev/LLM only classify.") {
            CampTextField(title: "http://127.0.0.1:8788", text: $store.draft.connections.recommendationURL)
            HStack {
                if let health = store.recommenderHealth {
                    CampBadge(text: "Connected · \(health["classifier"]?.string ?? "?")", active: true)
                    Text("\(health["restaurants"]?.int ?? 0) restaurants · \(health["items"]?.int ?? 0) items · \(health["users"]?.int ?? 0) users")
                        .font(.caption).foregroundStyle(CampPalette.muted)
                } else {
                    CampBadge(text: "Not connected")
                }
            }
            HStack {
                Button(store.recommenderBusy ? "Working…" : "Connect / refresh") { Task { await store.connectRecommender() } }
                    .buttonStyle(CampActionStyle(primary: false)).disabled(store.recommenderBusy)
                Button("Request lunch offer") { Task { await store.requestOffer() } }
                    .buttonStyle(CampActionStyle()).disabled(store.recommenderBusy || store.recommenderHealth == nil)
            }
            if let id = store.recommenderUserID { Text("Your recommender profile: \(id)").font(.caption).textSelection(.enabled).foregroundStyle(CampPalette.muted) }
            if let error = store.recommenderError { Text(error).font(.callout).foregroundStyle(.red).textSelection(.enabled) }
            Text("Sends your saved preferences, allergies, lunch window, office policy and presence preview. Prices come back as all-in estimates under the office batch; no order is placed.")
                .font(.caption).foregroundStyle(CampPalette.muted)
        }.onChange(of: store.draft.connections.recommendationURL) { _ in store.recommenderHealth = nil }
    }
}
