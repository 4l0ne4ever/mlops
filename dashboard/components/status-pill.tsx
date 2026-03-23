export function StatusPill({ label }: { label: string }) {
  const tone = label.toLowerCase();

  let className = "pill pill-neutral";
  if (
    ["healthy", "promoted", "deployed", "completed", "auto_promote"].includes(
      tone,
    )
  ) {
    className = "pill pill-good";
  } else if (["warning", "pending", "no_action", "escalate"].includes(tone)) {
    className = "pill pill-warn";
  } else if (
    [
      "failed",
      "rollback",
      "rolled_back",
      "critical_regression",
      "unhealthy",
      "timeout",
      "error",
      "unreachable",
    ].includes(tone)
  ) {
    className = "pill pill-bad";
  }

  return <span className={className}>{label.replaceAll("_", " ")}</span>;
}
