import "./globals.css";
export const metadata = {
  title: "マジョリティ · 今夜はどっち？",
  description: "友だちと楽しむリアルタイム二択パーティーゲーム",
};
export const viewport = { themeColor: "#f3efe4", colorScheme: "light" };

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ja"><body><a className="skip-link" href="#main-content">メインコンテンツへ移動</a>{children}</body></html>;
}
