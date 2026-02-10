import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Sidebar } from "@/components/Sidebar";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Mission Control — Forge OS",
  description: "Orchestration dashboard for the Forge OS semantic DAG",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 ml-56 p-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
