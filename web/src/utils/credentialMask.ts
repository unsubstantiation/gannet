// Mirrors backend credential masking for ordinary stream URLs. The backend
// also handles percent-encoded URLs in native log and error text.
const CREDENTIAL_QUERY_KEYS =
  "(?:user(?:name)?|usr|login|pass(?:word|wd)?|pwd|(?:[a-z_]*_)?token|(?:[a-z_]*_)?secret|client_private|api_?key)";
const URL_USERINFO_PATTERN =
  /:\/\/((?:[^\s/?#:[\]]*:(?:(?!:\/\/)\S)*|[^\s/?#]+))@((?:(?!:\/\/)\S)*)/g;
const CREDENTIAL_QUERY_KEY_PATTERN = new RegExp(
  `[?&]${CREDENTIAL_QUERY_KEYS}=`,
  "i",
);
const CREDENTIAL_QUERY_PATTERN = new RegExp(
  `([?&]${CREDENTIAL_QUERY_KEYS}=)[^&\\s]*`,
  "gi",
);
const PROTECT_TOKEN_PATTERN =
  /(rtsps?:\/\/[^\s/?#]+:744[17]\/)(?:(?!,rtsps?:\/\/)[^/?#\s])+/gi;
// Hide the entire credential portion of XMEye-style paths, including the
// underscore form returned by some ONVIF devices. Allow an unescaped comma in
// credentials, but stop at a subsequent comma-separated RTSP URL.
const XMEYE_AUTH_PATH_PATTERN =
  /(rtsps?:\/\/[^\s/?#]+\/(?:[^/\s?#]+\/)*?)user=((?:(?!,rtsps?:\/\/)[^\r\n])*)/gi;
const XMEYE_SAFE_SUFFIX_PATTERN =
  /([&_]channel=\d+[&_]stream=\d+(?:[&_]onvif=\d+)?\.sdp(?:\?real_stream|\?)?)$/i;
const MASKED_PATTERN = new RegExp(
  `://\\*:\\*@|[?&]${CREDENTIAL_QUERY_KEYS}=\\*(?![^&\\s])|rtsps?://[^\\s/?#]+:744[17]/\\*(?=[/?#\\s,]|$)|rtsps?://[^\\s/?#]+/(?:[^/\\s?#]+/)*user=\\*(?=[&_?]|$)`,
  "i",
);

/** UniFi Protect's standard RTSP(S) URLs use the path as a bearer token. */
export const maskProtectStreamToken = (value: string, mask = "*"): string =>
  value.replace(
    PROTECT_TOKEN_PATTERN,
    (_match, prefix: string) => `${prefix}${mask}`,
  );

/** XMEye credentials can contain delimiters, so preserve only a safe suffix. */
export const maskXmeyePath = (value: string, mask = "*"): string =>
  value.replace(
    XMEYE_AUTH_PATH_PATTERN,
    (_match, prefix: string, credentialAndSuffix: string) => {
      const suffix = credentialAndSuffix.match(XMEYE_SAFE_SUFFIX_PATTERN)?.[1];
      return `${prefix}user=${mask}${suffix ?? ""}`;
    },
  );

export const isMaskedPath = (value: string): boolean =>
  MASKED_PATTERN.test(value);

export const maskCredentials = (value: string): string => {
  if (!value) {
    return value;
  }

  // Mask path secrets first: an @ there is not necessarily URL userinfo.
  const withoutUserinfo = maskProtectStreamToken(maskXmeyePath(value)).replace(
    URL_USERINFO_PATTERN,
    (_match, userinfo: string, rest: string) =>
      CREDENTIAL_QUERY_KEY_PATTERN.test(userinfo)
        ? "://*:*@"
        : `://*:*@${rest}`,
  );
  return maskProtectStreamToken(maskXmeyePath(withoutUserinfo)).replace(
    CREDENTIAL_QUERY_PATTERN,
    "$1*",
  );
};

export const hasCredentials = (value: string): boolean =>
  !!value && (isMaskedPath(value) || maskCredentials(value) !== value);
