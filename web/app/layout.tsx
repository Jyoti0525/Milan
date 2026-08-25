import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Milan — settlement reconciliation",
  description: "Every rupee accounted for, or an exception that says why not.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="h-full antialiased">{children}</body>
    </html>
  );
}
