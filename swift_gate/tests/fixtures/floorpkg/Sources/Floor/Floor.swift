/// The sign of a reading: the one function this fixture's tests must cover fully.
public enum Sign: Equatable, Sendable {
  case negative
  case zero
  case positive
}

/// Classifies `value` by its sign, one outcome per case of ``Sign``.
public func classify(_ value: Int) -> Sign {
  if value < 0 {
    return .negative
  }
  return value == 0 ? .zero : .positive
}

/// A label for `value`, for reading a value by hand in the debugger; no test calls it.
public func debugLabel(_ value: Int) -> String {  // coverage: ignore: a debugger-only aid
  "\(value) is \(classify(value))"
}
