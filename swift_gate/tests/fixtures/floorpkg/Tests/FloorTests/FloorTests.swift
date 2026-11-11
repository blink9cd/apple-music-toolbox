import Testing

@testable import Floor

@Test func negativeValuesAreNegative() {
  #expect(classify(-4) == .negative)
}

@Test func zeroIsZero() {
  #expect(classify(0) == .zero)
}

@Test func positiveValuesArePositive() {
  #expect(classify(7) == .positive)
}
