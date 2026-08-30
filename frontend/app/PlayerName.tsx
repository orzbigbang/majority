export function PlayerName({ name }: { name: string }) {
  return <span className="player-name"><span className="player-name-value">{name}</span><span className="player-name-honorific">様</span></span>;
}
