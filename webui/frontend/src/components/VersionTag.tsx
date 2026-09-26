import type { Status } from "../api";

// Which build is running, beside Settings on every page (webui-spec 4.1): the release,
// and the branch and commit when the image was built with them. For reports.
export function versionText(v: Status["version"] | undefined): string {
  if (!v) return "";
  return [v.release ? `v${v.release}` : "version unknown", v.branch, v.commit].filter(Boolean).join(" · ");
}

export function VersionTag({ version }: { version: Status["version"] | undefined }) {
  const text = versionText(version);
  if (!text) return null;
  return (
    <span className="version-tag" title={`NegativeSpace ${text}. Include this in a report.`}>{text}</span>
  );
}
