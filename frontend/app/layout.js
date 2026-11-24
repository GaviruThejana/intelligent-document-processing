import "./globals.css";
import Link from "next/link";

export const metadata = { title: "Document Processing & Validation" };

export default function RootLayout({ children }) {
  return (
    <html lang="en"><body>
      <header><Link href="/">Document Processing &amp; Validation</Link></header>
      <main>{children}</main>
    </body></html>
  );
}
