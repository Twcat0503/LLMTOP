# Security

LLMTOP 0.1.x is an alpha baseline. It reads explicitly configured metrics and local hardware. The Web backend binds to loopback and accepts read-only requests; public or multi-user hosting is not currently supported. Keep engine credentials in server-side environment variables.

## Reporting

A public repository and private reporting channel have not yet been configured. Until one exists, report privately to the maintainer who provided your copy. Do not publish credentials, private endpoint inventories, request content or raw telemetry in an issue. Once hosting is configured, the release checklist requires a concrete private reporting route before public publication.

Include the LLMTOP version, affected component, minimal sanitized reproduction and expected impact. Hardware and upstream engine versions help reproduce adapter behavior. Avoid testing against systems you do not control or sending inference traffic without authorization.

## Data handling

Configuration validation errors are sanitized. Missing observations remain N/A with a reason. Browser clients receive normalized snapshots, without engine authorization headers or environment values. The release audit checks candidate source files and built packages for excluded private files and configured private patterns; it does not replace review of fixtures, screenshots and third-party licenses.
