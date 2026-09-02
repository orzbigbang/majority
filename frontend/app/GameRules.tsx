import { defaultGameRuleSpec, gameRulesCopy, GameRuleSpec } from "./ja";

export function GameRules({ rules = defaultGameRuleSpec }: { rules?: GameRuleSpec }) {
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
      <div className="rule-visual rule-choice-visual" aria-hidden="true">
        <span className="rule-choice-card rule-choice-yes">●<small>{gameRulesCopy.choices.yes}</small></span>
        <div className="rule-button"><i /></div>
        <span className="rule-choice-card rule-choice-no">—<small>{gameRulesCopy.choices.no}</small></span>
      </div>
      <div className="rule-copy"><span>2</span><div><h3>{gameRulesCopy.steps[1].title}</h3><p>{gameRulesCopy.steps[1].description}</p></div></div>
    </article>

    <article className="rule-step">
      <div className="rule-visual rule-majority-visual" aria-hidden="true">
        <div className="rule-crown">★</div>
        <div className="rule-people">
          <i className="majority-person" /><i className="majority-person" /><i className="majority-person" />
          <i /><i />
        </div>
        <strong>+{rules.majority_reward}</strong>
      </div>
      <div className="rule-copy"><span>3</span><div><h3>{gameRulesCopy.steps[2].title(rules)}</h3><p>{gameRulesCopy.steps[2].description(rules)}</p></div></div>
    </article>

    <p className="rules-loop"><span aria-hidden="true">↻</span> {gameRulesCopy.loop(rules)}</p>
  </div>;
}
