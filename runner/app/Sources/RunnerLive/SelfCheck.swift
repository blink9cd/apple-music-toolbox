// The runner's check of its own bundle. macOS does not re-check a bundle's resources at
// launch, so this check is what makes an edited Info.plist allowlist refuse to run.
import Foundation
import Security

/// Verifies the running bundle's static code signature.
public enum SelfCheck {
  /// The bundle's static signature, resources and Info.plist included, is valid.
  public static func bundleIsIntact() -> Bool {
    var code: SecStaticCode?
    guard
      SecStaticCodeCreateWithPath(Bundle.main.bundleURL as CFURL, [], &code) == errSecSuccess,
      let code
    else { return false }
    let flags = SecCSFlags(rawValue: kSecCSCheckAllArchitectures)
    return SecStaticCodeCheckValidity(code, flags, nil) == errSecSuccess
  }
}
