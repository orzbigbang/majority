import "./globals.css";
export const metadata = { title: "Party Quiz", description: "Real-time party quiz" };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="zh-CN"><body>{children}</body></html>; }
