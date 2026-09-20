import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

public enum LunchStyle {
    public static let ink = Color(red: 0.08, green: 0.12, blue: 0.10)
    public static let lime = Color(red: 0.79, green: 0.95, blue: 0.43)
    public static let muted = Color.white.opacity(0.62)

    public static func money(_ cents: Int) -> String {
        (Double(cents) / 100).formatted(.currency(code: "USD"))
    }
}

/// Actions are injected: ordinary buttons in the app/preview, intent buttons in
/// the Live Activity. All surfaces use exactly the same meal and status layout.
public struct LunchCard<Actions: View>: View {
    let session: LunchSession
    let expired: Bool
    let embedded: Bool
    let actions: Actions

    public init(session: LunchSession, expired: Bool = false, embedded: Bool = false, @ViewBuilder actions: () -> Actions) {
        self.session = session
        self.expired = expired
        self.embedded = embedded
        self.actions = actions()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                // The notch supplies its own persistent branded header.
                if !embedded {
                    CampLogo().fill(LunchStyle.lime).frame(width: 30, height: 18).accessibilityHidden(true)
                    Text("camp").font(.system(size: 22, weight: .bold, design: .rounded)).tracking(-0.8)
                }
                Spacer(minLength: 4)
                Text("DEMO").font(.system(size: 9, weight: .bold)).foregroundStyle(LunchStyle.muted)
                if !expired && (session.phase == .choosing || session.phase == .reviewing) {
                    Text(timerInterval: min(Date.now, session.closesAt)...session.closesAt, countsDown: true)
                        .monospacedDigit().font(.caption.weight(.semibold)).frame(width: 42)
                        .accessibilityLabel("Time left to choose")
                }
            }
            if expired {
                status("This lunch window closed", detail: "Open camp to start a fresh demo.", symbol: "clock")
            } else {
                switch session.phase {
                case .choosing:
                    HStack(alignment: .firstTextBaseline) {
                        Text("Lunch, sorted.").font(.system(size: 21, weight: .semibold, design: .rounded))
                        Spacer(minLength: 4)
                        arrival
                    }
                    actions
                case .reviewing:
                    if let option = session.selectedOption {
                        HStack(spacing: 8) {
                            MealLabel(option: option)
                        }
                        HStack {
                            Text("Save \(LunchStyle.money(option.savingsCents)) in this demo")
                                .foregroundStyle(LunchStyle.lime)
                            Spacer(minLength: 4)
                            arrival
                        }.font(.caption)
                        actions
                    }
                case .confirmed:
                    status("You're on the list.", detail: session.selectedOption?.name ?? "Lunch confirmed", symbol: "checkmark.circle.fill")
                    HStack {
                        Text("Demo choice saved · no order placed")
                        Spacer(minLength: 4)
                        arrival
                    }.font(.caption2).foregroundStyle(LunchStyle.muted)
                case .delivered:
                    status("Lunch has landed.", detail: "Demo complete. Enjoy your break.", symbol: "bag.fill")
                case .ended:
                    status("Lunch ended", detail: "Start a new session whenever you're ready.", symbol: "moon.fill")
                }
            }
        }
        .foregroundStyle(.white)
        .padding(16)
        .background(embedded ? Color.clear : LunchStyle.ink)
        .clipShape(RoundedRectangle(cornerRadius: 22))
    }

    private var arrival: some View {
        HStack(spacing: 3) {
            Image(systemName: "bag")
            Text(session.arrivesAt, style: .time)
        }.font(.caption2).foregroundStyle(LunchStyle.muted)
    }

    private func status(_ title: String, detail: String, symbol: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).font(.title2).foregroundStyle(LunchStyle.lime)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 20, weight: .semibold, design: .rounded))
                Text(detail).font(.caption).foregroundStyle(LunchStyle.muted)
            }
        }
    }
}

public struct MealLabel: View {
    let option: LunchOption
    public init(option: LunchOption) { self.option = option }
    public var body: some View {
        HStack(spacing: 10) {
            Image(systemName: option.symbol).font(.system(size: 16))
                .foregroundStyle(LunchStyle.lime).frame(width: 26)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(option.name).font(.system(size: 13, weight: .semibold))
                Text(option.detail).font(.system(size: 10)).foregroundStyle(LunchStyle.muted)
            }
            Spacer(minLength: 4)
            Text(LunchStyle.money(option.priceCents)).font(.system(size: 13, weight: .semibold)).monospacedDigit()
        }.foregroundStyle(.white).frame(maxWidth: .infinity, alignment: .leading)
    }
}

public struct MealButtonStyle: ButtonStyle {
    public init() {}
    public func makeBody(configuration: Configuration) -> some View {
        configuration.label.padding(.horizontal, 10).padding(.vertical, 9)
            .background(Color.white.opacity(configuration.isPressed ? 0.18 : 0.07))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .contentShape(RoundedRectangle(cornerRadius: 12))
    }
}

public struct ConfirmLabel: View {
    public init() {}
    public var body: some View {
        Text("Confirm lunch").font(.system(size: 13, weight: .semibold))
            .foregroundStyle(LunchStyle.ink).frame(maxWidth: .infinity).padding(.vertical, 11)
            .background(LunchStyle.lime).clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

public struct LocalLunchCard: View {
    let session: LunchSession
    let embedded: Bool
    let send: (LunchEvent) -> Void
    public init(session: LunchSession, embedded: Bool = false, send: @escaping (LunchEvent) -> Void) {
        self.session = session
        self.embedded = embedded
        self.send = send
    }
    public var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            LunchCard(session: session, expired: session.isExpired(at: context.date), embedded: embedded) {
                if session.phase == .choosing {
                    VStack(spacing: 5) {
                        ForEach(session.options) { option in
                            Button { send(.select(option.id)) } label: { MealLabel(option: option) }
                                .buttonStyle(MealButtonStyle())
                        }
                    }
                } else if session.phase == .reviewing {
                    HStack(spacing: 12) {
                        Button("Change") { send(.changeSelection) }
                            .font(.caption.weight(.semibold)).buttonStyle(.plain)
                        Button { send(.confirm) } label: { ConfirmLabel() }.buttonStyle(.plain)
                    }
                }
            }
        }
    }
}

/// Vector mark from Branding/camp.svg; the source's white background is omitted.
/// Coordinates are cached and fitted without stretching or raster assets.
public struct CampLogo: Shape {
    public init() {}
    public static let aspectRatio: CGFloat = 925.0 / 470.0
    private static let mark: Path = {
        var path = Path()
        let outlines = "M 980.0 455.0 L 978.0 454.0 L 973.0 454.0 L 972.0 453.0 L 969.0 453.0 L 968.0 452.0 L 964.0 452.0 L 963.0 451.0 L 959.0 451.0 L 958.0 450.0 L 955.0 450.0 L 954.0 449.0 L 951.0 449.0 L 950.0 448.0 L 947.0 448.0 L 946.0 447.0 L 943.0 447.0 L 942.0 446.0 L 935.0 445.0 L 934.0 444.0 L 932.0 444.0 L 928.0 442.0 L 925.0 442.0 L 924.0 441.0 L 922.0 441.0 L 921.0 440.0 L 919.0 440.0 L 918.0 439.0 L 910.0 437.0 L 907.0 435.0 L 899.0 433.0 L 896.0 431.0 L 894.0 431.0 L 891.0 429.0 L 889.0 429.0 L 886.0 427.0 L 884.0 427.0 L 879.0 424.0 L 877.0 424.0 L 870.0 420.0 L 868.0 420.0 L 848.0 410.0 L 846.0 408.0 L 837.0 404.0 L 835.0 402.0 L 830.0 400.0 L 820.0 393.0 L 817.0 392.0 L 812.0 388.0 L 809.0 387.0 L 806.0 384.0 L 805.0 384.0 L 803.0 382.0 L 796.0 378.0 L 793.0 375.0 L 792.0 375.0 L 789.0 372.0 L 788.0 372.0 L 785.0 369.0 L 784.0 369.0 L 781.0 366.0 L 780.0 366.0 L 777.0 363.0 L 776.0 363.0 L 771.0 358.0 L 770.0 358.0 L 766.0 354.0 L 765.0 354.0 L 758.0 347.0 L 757.0 347.0 L 747.0 337.0 L 746.0 337.0 L 726.0 317.0 L 726.0 316.0 L 716.0 306.0 L 716.0 305.0 L 705.0 293.0 L 705.0 292.0 L 697.0 283.0 L 697.0 282.0 L 688.0 271.0 L 686.0 267.0 L 683.0 264.0 L 683.0 263.0 L 671.0 246.0 L 667.0 238.0 L 663.0 233.0 L 660.0 226.0 L 658.0 224.0 L 655.0 217.0 L 653.0 215.0 L 644.0 197.0 L 644.0 195.0 L 639.0 186.0 L 639.0 184.0 L 637.0 181.0 L 637.0 179.0 L 634.0 174.0 L 634.0 172.0 L 632.0 169.0 L 631.0 164.0 L 629.0 161.0 L 629.0 159.0 L 628.0 158.0 L 626.0 150.0 L 624.0 147.0 L 624.0 145.0 L 622.0 141.0 L 622.0 138.0 L 620.0 134.0 L 620.0 131.0 L 618.0 127.0 L 618.0 124.0 L 616.0 120.0 L 616.0 117.0 L 615.0 116.0 L 615.0 113.0 L 614.0 112.0 L 614.0 108.0 L 613.0 107.0 L 613.0 104.0 L 612.0 103.0 L 612.0 99.0 L 611.0 98.0 L 611.0 94.0 L 610.0 93.0 L 610.0 88.0 L 609.0 87.0 L 609.0 82.0 L 608.0 81.0 L 608.0 76.0 L 607.0 75.0 L 607.0 68.0 L 606.0 67.0 L 606.0 58.0 L 605.0 57.0 L 605.0 55.0 L 603.0 57.0 L 602.0 57.0 L 595.0 64.0 L 594.0 64.0 L 587.0 71.0 L 586.0 71.0 L 579.0 78.0 L 578.0 78.0 L 570.0 86.0 L 569.0 86.0 L 561.0 94.0 L 560.0 94.0 L 552.0 102.0 L 551.0 102.0 L 543.0 110.0 L 542.0 110.0 L 518.0 132.0 L 516.0 132.0 L 494.0 112.0 L 493.0 112.0 L 486.0 105.0 L 485.0 105.0 L 471.0 92.0 L 470.0 92.0 L 464.0 86.0 L 463.0 86.0 L 457.0 80.0 L 456.0 80.0 L 449.0 73.0 L 448.0 73.0 L 442.0 67.0 L 441.0 67.0 L 436.0 62.0 L 435.0 62.0 L 430.0 57.0 L 429.0 57.0 L 429.0 65.0 L 428.0 66.0 L 427.0 80.0 L 426.0 81.0 L 426.0 86.0 L 425.0 87.0 L 424.0 98.0 L 423.0 99.0 L 423.0 103.0 L 422.0 104.0 L 422.0 107.0 L 421.0 108.0 L 421.0 112.0 L 420.0 113.0 L 419.0 120.0 L 417.0 124.0 L 417.0 127.0 L 416.0 128.0 L 416.0 130.0 L 415.0 131.0 L 415.0 133.0 L 413.0 137.0 L 413.0 140.0 L 412.0 141.0 L 411.0 146.0 L 409.0 149.0 L 407.0 157.0 L 405.0 160.0 L 405.0 162.0 L 403.0 165.0 L 403.0 167.0 L 401.0 170.0 L 401.0 172.0 L 398.0 177.0 L 398.0 179.0 L 393.0 188.0 L 393.0 190.0 L 385.0 206.0 L 383.0 208.0 L 380.0 215.0 L 378.0 217.0 L 376.0 222.0 L 374.0 224.0 L 373.0 227.0 L 371.0 229.0 L 367.0 237.0 L 365.0 239.0 L 365.0 240.0 L 363.0 242.0 L 363.0 243.0 L 361.0 245.0 L 361.0 246.0 L 359.0 248.0 L 355.0 255.0 L 352.0 258.0 L 348.0 265.0 L 341.0 273.0 L 341.0 274.0 L 338.0 277.0 L 338.0 278.0 L 330.0 287.0 L 330.0 288.0 L 318.0 301.0 L 318.0 302.0 L 306.0 314.0 L 306.0 315.0 L 278.0 342.0 L 277.0 342.0 L 270.0 349.0 L 269.0 349.0 L 264.0 354.0 L 263.0 354.0 L 254.0 362.0 L 253.0 362.0 L 234.0 377.0 L 233.0 377.0 L 213.0 391.0 L 210.0 392.0 L 208.0 394.0 L 205.0 395.0 L 203.0 397.0 L 195.0 401.0 L 193.0 403.0 L 184.0 407.0 L 182.0 409.0 L 152.0 424.0 L 150.0 424.0 L 143.0 428.0 L 141.0 428.0 L 138.0 430.0 L 136.0 430.0 L 131.0 433.0 L 129.0 433.0 L 121.0 437.0 L 119.0 437.0 L 118.0 438.0 L 116.0 438.0 L 115.0 439.0 L 113.0 439.0 L 112.0 440.0 L 110.0 440.0 L 109.0 441.0 L 107.0 441.0 L 106.0 442.0 L 104.0 442.0 L 103.0 443.0 L 101.0 443.0 L 100.0 444.0 L 98.0 444.0 L 94.0 446.0 L 91.0 446.0 L 87.0 448.0 L 80.0 449.0 L 79.0 450.0 L 73.0 451.0 L 72.0 452.0 L 69.0 452.0 L 68.0 453.0 L 64.0 453.0 L 63.0 454.0 L 55.0 455.0 L 55.0 456.0 L 121.0 525.0 L 127.0 525.0 L 128.0 524.0 L 134.0 524.0 L 135.0 523.0 L 139.0 523.0 L 140.0 522.0 L 145.0 522.0 L 146.0 521.0 L 149.0 521.0 L 150.0 520.0 L 154.0 520.0 L 155.0 519.0 L 158.0 519.0 L 159.0 518.0 L 162.0 518.0 L 163.0 517.0 L 166.0 517.0 L 167.0 516.0 L 174.0 515.0 L 178.0 513.0 L 181.0 513.0 L 182.0 512.0 L 184.0 512.0 L 185.0 511.0 L 187.0 511.0 L 188.0 510.0 L 190.0 510.0 L 191.0 509.0 L 193.0 509.0 L 194.0 508.0 L 196.0 508.0 L 197.0 507.0 L 199.0 507.0 L 200.0 506.0 L 202.0 506.0 L 203.0 505.0 L 211.0 503.0 L 214.0 501.0 L 216.0 501.0 L 222.0 498.0 L 224.0 498.0 L 227.0 496.0 L 229.0 496.0 L 245.0 488.0 L 247.0 488.0 L 277.0 473.0 L 279.0 471.0 L 291.0 465.0 L 293.0 463.0 L 296.0 462.0 L 304.0 456.0 L 307.0 455.0 L 309.0 453.0 L 316.0 449.0 L 319.0 446.0 L 323.0 444.0 L 326.0 441.0 L 327.0 441.0 L 337.0 433.0 L 338.0 433.0 L 342.0 429.0 L 343.0 429.0 L 347.0 425.0 L 348.0 425.0 L 353.0 420.0 L 354.0 420.0 L 360.0 414.0 L 361.0 414.0 L 368.0 407.0 L 369.0 407.0 L 401.0 375.0 L 401.0 374.0 L 414.0 360.0 L 414.0 359.0 L 419.0 354.0 L 419.0 353.0 L 426.0 345.0 L 426.0 344.0 L 429.0 341.0 L 429.0 340.0 L 433.0 336.0 L 437.0 329.0 L 445.0 319.0 L 446.0 316.0 L 454.0 305.0 L 455.0 302.0 L 457.0 300.0 L 458.0 297.0 L 463.0 290.0 L 465.0 285.0 L 467.0 283.0 L 471.0 274.0 L 473.0 272.0 L 476.0 266.0 L 476.0 264.0 L 483.0 251.0 L 483.0 249.0 L 487.0 242.0 L 487.0 240.0 L 489.0 237.0 L 489.0 235.0 L 493.0 227.0 L 494.0 222.0 L 496.0 219.0 L 496.0 217.0 L 497.0 216.0 L 497.0 214.0 L 498.0 213.0 L 498.0 211.0 L 499.0 210.0 L 499.0 208.0 L 501.0 204.0 L 501.0 201.0 L 502.0 200.0 L 502.0 198.0 L 503.0 197.0 L 503.0 195.0 L 505.0 191.0 L 505.0 188.0 L 506.0 187.0 L 506.0 184.0 L 507.0 183.0 L 507.0 180.0 L 508.0 179.0 L 508.0 176.0 L 509.0 175.0 L 509.0 171.0 L 510.0 170.0 L 511.0 162.0 L 512.0 161.0 L 513.0 153.0 L 514.0 152.0 L 514.0 147.0 L 515.0 146.0 L 516.0 135.0 L 517.0 134.0 L 519.0 138.0 L 519.0 143.0 L 520.0 144.0 L 521.0 155.0 L 522.0 156.0 L 522.0 160.0 L 523.0 161.0 L 523.0 164.0 L 524.0 165.0 L 524.0 169.0 L 525.0 170.0 L 525.0 173.0 L 526.0 174.0 L 526.0 177.0 L 527.0 178.0 L 527.0 181.0 L 528.0 182.0 L 529.0 189.0 L 531.0 193.0 L 531.0 196.0 L 532.0 197.0 L 532.0 199.0 L 534.0 203.0 L 534.0 206.0 L 535.0 207.0 L 535.0 209.0 L 536.0 210.0 L 536.0 212.0 L 537.0 213.0 L 539.0 221.0 L 541.0 224.0 L 542.0 229.0 L 544.0 232.0 L 544.0 234.0 L 546.0 237.0 L 546.0 239.0 L 549.0 244.0 L 549.0 246.0 L 552.0 251.0 L 552.0 253.0 L 558.0 264.0 L 558.0 266.0 L 560.0 268.0 L 568.0 285.0 L 570.0 287.0 L 572.0 292.0 L 574.0 294.0 L 575.0 297.0 L 577.0 299.0 L 581.0 307.0 L 583.0 309.0 L 583.0 310.0 L 585.0 312.0 L 585.0 313.0 L 587.0 315.0 L 587.0 316.0 L 589.0 318.0 L 593.0 325.0 L 596.0 328.0 L 600.0 335.0 L 607.0 343.0 L 607.0 344.0 L 610.0 347.0 L 610.0 348.0 L 614.0 352.0 L 614.0 353.0 L 618.0 357.0 L 618.0 358.0 L 624.0 364.0 L 624.0 365.0 L 630.0 371.0 L 630.0 372.0 L 642.0 384.0 L 642.0 385.0 L 671.0 413.0 L 672.0 413.0 L 678.0 419.0 L 679.0 419.0 L 684.0 424.0 L 685.0 424.0 L 694.0 432.0 L 695.0 432.0 L 702.0 438.0 L 706.0 440.0 L 713.0 446.0 L 714.0 446.0 L 728.0 456.0 L 731.0 457.0 L 736.0 461.0 L 739.0 462.0 L 741.0 464.0 L 744.0 465.0 L 751.0 470.0 L 756.0 472.0 L 758.0 474.0 L 792.0 491.0 L 794.0 491.0 L 797.0 493.0 L 799.0 493.0 L 804.0 496.0 L 806.0 496.0 L 814.0 500.0 L 816.0 500.0 L 817.0 501.0 L 819.0 501.0 L 820.0 502.0 L 822.0 502.0 L 823.0 503.0 L 825.0 503.0 L 826.0 504.0 L 828.0 504.0 L 829.0 505.0 L 831.0 505.0 L 832.0 506.0 L 834.0 506.0 L 835.0 507.0 L 837.0 507.0 L 838.0 508.0 L 840.0 508.0 L 844.0 510.0 L 847.0 510.0 L 851.0 512.0 L 854.0 512.0 L 855.0 513.0 L 858.0 513.0 L 859.0 514.0 L 862.0 514.0 L 863.0 515.0 L 866.0 515.0 L 867.0 516.0 L 870.0 516.0 L 871.0 517.0 L 875.0 517.0 L 876.0 518.0 L 880.0 518.0 L 881.0 519.0 L 886.0 519.0 L 887.0 520.0 L 891.0 520.0 L 892.0 521.0 L 905.0 522.0 L 906.0 523.0 L 914.0 523.0 Z|M 255.0 523.0 L 509.0 523.0 L 507.0 521.0 L 505.0 517.0 L 502.0 514.0 L 502.0 513.0 L 499.0 510.0 L 499.0 509.0 L 496.0 506.0 L 496.0 505.0 L 491.0 499.0 L 489.0 495.0 L 483.0 488.0 L 481.0 484.0 L 475.0 477.0 L 473.0 473.0 L 464.0 462.0 L 462.0 458.0 L 456.0 451.0 L 360.0 451.0 L 350.0 458.0 L 349.0 458.0 L 347.0 460.0 L 346.0 460.0 L 344.0 462.0 L 343.0 462.0 L 340.0 465.0 L 339.0 465.0 L 337.0 467.0 L 336.0 467.0 L 334.0 469.0 L 327.0 473.0 L 324.0 476.0 L 323.0 476.0 L 321.0 478.0 L 320.0 478.0 L 318.0 480.0 L 317.0 480.0 L 315.0 482.0 L 308.0 486.0 L 305.0 489.0 L 304.0 489.0 L 302.0 491.0 L 295.0 495.0 L 292.0 498.0 L 291.0 498.0 L 289.0 500.0 L 288.0 500.0 L 286.0 502.0 L 279.0 506.0 L 276.0 509.0 L 275.0 509.0 Z|M 525.0 522.0 L 528.0 522.0 L 529.0 523.0 L 566.0 523.0 L 567.0 522.0 L 578.0 522.0 L 579.0 523.0 L 580.0 522.0 L 586.0 522.0 L 587.0 523.0 L 588.0 522.0 L 589.0 523.0 L 609.0 523.0 L 610.0 522.0 L 615.0 522.0 L 616.0 523.0 L 628.0 523.0 L 629.0 522.0 L 774.0 522.0 L 769.0 518.0 L 762.0 514.0 L 759.0 511.0 L 752.0 507.0 L 749.0 504.0 L 745.0 502.0 L 742.0 499.0 L 741.0 499.0 L 739.0 497.0 L 732.0 493.0 L 729.0 490.0 L 722.0 486.0 L 719.0 483.0 L 712.0 479.0 L 709.0 476.0 L 702.0 472.0 L 699.0 469.0 L 698.0 469.0 L 696.0 467.0 L 689.0 463.0 L 686.0 460.0 L 679.0 456.0 L 673.0 451.0 L 577.0 451.0 Z".split(separator: "|")
        for outline in outlines {
            let tokens = outline.split(separator: " ")
            var index = 0
            while index < tokens.count {
                let command = tokens[index]; index += 1
                if command == "Z" { path.closeSubpath(); continue }
                guard index + 1 < tokens.count,
                      let x = Double(tokens[index]), let y = Double(tokens[index + 1]) else { break }
                index += 2
                let point = CGPoint(x: x - 55.0, y: y - 55.0)
                if command == "M" { path.move(to: point) }
                else if command == "L" { path.addLine(to: point) }
            }
        }
        return path
    }()
    public func path(in rect: CGRect) -> Path {
        let scale = min(rect.width / 925.0, rect.height / 470.0)
        return Self.mark.applying(CGAffineTransform(scaleX: scale, y: scale))
            .applying(CGAffineTransform(translationX: rect.midX - 925.0 * scale / 2,
                                       y: rect.midY - 470.0 * scale / 2))
    }
}
