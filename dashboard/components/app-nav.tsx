import Link from "next/link";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/versions", label: "Version History" },
  { href: "/drift", label: "Metric Drift" },
  { href: "/runs", label: "Pipeline Runs" },
  { href: "/compare", label: "Comparison" },
];

export function AppNav() {
  return (
    <nav className="topbar">
      <div>
        <p className="eyebrow">AgentOps Platform</p>
        <h1>Production Control Room</h1>
      </div>
      <div className="nav-links">
        {NAV_ITEMS.map((item) => (
          <Link key={item.href} href={item.href} className="nav-link">
            {item.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
