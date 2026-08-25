import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

/*
  Blade sets its text in Inter and its code in a mono face. Inter is the same
  choice here; the mono is JetBrains Mono rather than Blade's Menlo stack,
  because Menlo is a macOS system font and this has to look the same on the
  Windows machine it is demonstrated from.
*/
const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Milan — settlement reconciliation",
  description: "Every rupee accounted for, or an exception that says why not.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body className="h-full font-sans antialiased">{children}</body>
    </html>
  );
}
