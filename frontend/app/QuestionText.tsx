export function QuestionText({ title }: { title: string }) {
  const markerIndex = title.indexOf("しかし");
  if (markerIndex < 0) return <>{title}</>;

  const benefit = title.slice(0, markerIndex).trim();
  const consequence = title.slice(markerIndex + "しかし".length).trim();

  return <>
    <span className="question-benefit">{benefit}</span>
    <span className="shikashi-marker">しかし</span>
    <span className="question-consequence">{consequence}</span>
  </>;
}
