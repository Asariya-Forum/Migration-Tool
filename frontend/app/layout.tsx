import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "AsariyaForum Digital Library", description: "Local PDF migration and review dashboard" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
 return <html lang="en"><body>{children}</body></html>;
}
