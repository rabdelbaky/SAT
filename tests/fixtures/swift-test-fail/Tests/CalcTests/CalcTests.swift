import XCTest
@testable import Calc

final class CalcTests: XCTestCase {
    func testSum() {
        XCTAssertEqual(sum(2, 3), 6)
    }
}
