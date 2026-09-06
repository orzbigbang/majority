import { defaultGameRuleSpec, gameRulesCopy, GameRuleSpec } from "./ja";

export function GameRules({ rules = defaultGameRuleSpec }: { rules?: GameRuleSpec }) {
  const scoring = gameRulesCopy.scoring;
  const scoreRows = [scoring.majority, scoring.minority, scoring.parentMajority, scoring.parentMinority];

  return <div className="rules-guide">
    <article className="rule-step">
      <div className="rule-visual rule-card-visual" aria-hidden="true">
        <div className="rule-mini-card">
          <i />
          <b>{gameRulesCopy.conjunction}</b>
          <i />
        </div>
        <span className="rule-question-mark">?</span>
      </div>
      <div className="rule-copy"><span>1</span><div><h3>{gameRulesCopy.steps[0].title}</h3><p>{gameRulesCopy.steps[0].description}</p></div></div>
    </article>

    <article className="rule-step">
      <div className="rule-visual rule-secret-visual" aria-hidden="true">
        <span className="rule-parent-token">親</span>
        <div className="rule-secret-card"><i /><b>ひみつ</b></div>
      </div>
      <div className="rule-copy"><span>2</span><div><h3>{gameRulesCopy.steps[1].title}</h3><p>{gameRulesCopy.steps[1].description}</p></div></div>
    </article>

    <article className="rule-step">
      <div className="rule-visual rule-choice-visual" aria-hidden="true">
        <span className="rule-choice-card rule-choice-yes">●<small>{gameRulesCopy.choices.yes}</small></span>
        <div className="rule-button"><i /></div>
        <span className="rule-choice-card rule-choice-no">—<small>{gameRulesCopy.choices.no}</small></span>
      </div>
      <div className="rule-copy"><span>3</span><div><h3>{gameRulesCopy.steps[2].title}</h3><p>{gameRulesCopy.steps[2].description}</p></div></div>
    </article>

    <article className="rule-step rule-step-scoring">
      <div className="rule-visual rule-majority-visual" aria-hidden="true">
        <div className="rule-crown">★</div>
        <div className="rule-people">
          <i className="majority-person" /><i className="majority-person" /><i className="majority-person" />
          <i /><i />
        </div>
        <strong>+{rules.majority_reward}</strong>
      </div>
      <div className="rule-copy"><span>4</span><div><h3>{gameRulesCopy.steps[3].title(rules)}</h3><p>{gameRulesCopy.steps[3].description}</p><div className="rules-score-board"><strong className="rules-starting-score">{scoring.starting(rules)}</strong><dl>{scoreRows.map(row => <div key={row.label}><dt>{row.label}</dt><dd>{row.detail(rules)}</dd></div>)}</dl><p className="rules-score-example">{scoring.example(rules)}</p></div><ul className="rules-score-notes">{scoring.notes(rules).map(note => <li key={note}>{note}</li>)}</ul></div></div>
    </article>

    <p className="rules-loop"><span aria-hidden="true">↻</span> {gameRulesCopy.loop}</p>
  </div>;
}
