import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/layout/sidebar";
import { QueryProvider } from "@/components/providers/query-provider";

export const metadata: Metadata = {
  title: "Meridian — Quantitative Trading Platform",
  description: "AI-powered stock & crypto analysis with institutional-grade quant engine",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-background text-white antialiased">
        <QueryProvider>
          <Sidebar />
          <main className="lg:ml-56 min-h-screen">
            <div className="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8">
              {children}
            </div>
          </main>
        </QueryProvider>
      </body>
    </html>
  );
}
