export function GameRules() {
  return <div className="rules-guide">
    <article className="rule-step">
      <div className="rule-visual rule-card-visual" aria-hidden="true">
        <div className="rule-mini-card">
          <i />
          <b>しかし</b>
          <i />
        </div>
        <span className="rule-question-mark">?</span>
      </div>
      <div className="rule-copy"><span>1</span><div><h3>親が問題を選ぶ</h3><p>「しかし」の前後を読んで、迷いそうな一問を選びます。</p></div></div>
    </article>

    <article className="rule-step">
      <div className="rule-visual rule-choice-visual" aria-hidden="true">
        <span className="rule-choice-card rule-choice-yes">●<small>押す</small></span>
        <div className="rule-button"><i /></div>
        <span className="rule-choice-card rule-choice-no">—<small>押さない</small></span>
      </div>
      <div className="rule-copy"><span>2</span><div><h3>みんなで同時に選ぶ</h3><p>「押す」か「押さない」を決めて、回答を確定します。</p></div></div>
    </article>

    <article className="rule-step">
      <div className="rule-visual rule-majority-visual" aria-hidden="true">
        <div className="rule-crown">★</div>
        <div className="rule-people">
          <i className="majority-person" /><i className="majority-person" /><i className="majority-person" />
          <i /><i />
        </div>
        <strong>+1</strong>
      </div>
      <div className="rule-copy"><span>3</span><div><h3>多数派は＋1ポイント</h3><p>全員1点から開始。少数派は−1、その1点は親へ（親自身なら場へ）。0未満にはなりません。</p></div></div>
    </article>

    <p className="rules-loop"><span aria-hidden="true">↻</span> 同数なら親側が多数派。親を交代し、最後に最高得点の人が勝ち！</p>
  </div>;
}
