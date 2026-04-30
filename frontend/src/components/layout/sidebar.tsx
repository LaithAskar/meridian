"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { Home, PieChart, Landmark, Bitcoin, BarChart3, Brain, Menu, X, TrendingUp } from "lucide-react";

const staticLinks = [
  { href: "/", label: "Home", icon: Home },
  { href: "/portfolio", label: "Portfolio", icon: PieChart },
  { href: "/robinhood", label: "Robinhood", icon: Landmark },
  { href: "/crypto", label: "Crypto", icon: Bitcoin },
];

export function Sidebar() {
  const pathname = usePathname();
  const { currentTicker, sidebarOpen, setSidebarOpen } = useStore();

  const tickerLinks = [
    { href: `/analyze/${currentTicker}`, label: "Analysis", icon: BarChart3, prefix: "/analyze" },
    { href: `/predict/${currentTicker}`, label: "Predictions", icon: Brain, prefix: "/predict" },
  ];

  return (
    <>
      <button onClick={() => setSidebarOpen(!sidebarOpen)} className="fixed top-4 left-4 z-50 lg:hidden p-2 bg-card border border-border rounded-lg">
        {sidebarOpen ? <X size={18} /> : <Menu size={18} />}
      </button>

      <aside className={cn(
        "fixed top-0 left-0 h-full z-40 bg-card border-r border-border flex flex-col transition-transform duration-200",
        "w-56 lg:translate-x-0",
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      )}>
        {/* Logo */}
        <div className="p-5 border-b border-border">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center">
              <TrendingUp size={16} className="text-accent" />
            </div>
            <span className="text-lg font-semibold tracking-tight">Meridian</span>
          </Link>
        </div>

        {/* Static nav */}
        <nav className="flex-1 p-3 space-y-1">
          {staticLinks.map((link) => {
            const active = pathname === link.href;
            return (
              <Link key={link.href} href={link.href} className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                active ? "bg-accent/10 text-accent" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
              )}>
                <link.icon size={16} />
                {link.label}
              </Link>
            );
          })}

          {/* Divider */}
          <div className="pt-3 pb-1 px-3">
            <span className="text-[10px] font-medium text-gray-600 uppercase tracking-widest">
              {currentTicker || "Select Ticker"}
            </span>
          </div>

          {tickerLinks.map((link) => {
            const disabled = !currentTicker;
            const active = pathname.startsWith(link.prefix);
            return (
              <Link
                key={link.prefix}
                href={disabled ? "#" : link.href}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                  disabled && "opacity-30 cursor-not-allowed pointer-events-none",
                  active ? "bg-accent/10 text-accent" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                )}
                onClick={(e) => disabled && e.preventDefault()}
              >
                <link.icon size={16} />
                {link.label}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-border">
          <p className="text-[10px] text-gray-600 text-center">Meridian v1.0 — Not financial advice</p>
        </div>
      </aside>
    </>
  );
}
