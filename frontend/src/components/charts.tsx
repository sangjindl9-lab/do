// 실제 DB 집계 데이터를 그리는 SVG 차트. 강조색은 한 계열에만 쓴다.
export function StackedDays({ data, height = 280 }: { data: { day: string; passed: number; failed: number; error: number }[]; height?: number }) {
  if (!data.length) return <div className="flex items-center justify-center text-sm text-mute" style={{ height }}>아직 기록된 검사 결과가 없습니다</div>;
  const W = 720, pad = { l: 36, r: 8, t: 12, b: 28 };
  const max = Math.max(1, ...data.map((d) => d.passed + d.failed + d.error));
  const ih = height - pad.t - pad.b, iw = W - pad.l - pad.r;
  const bw = Math.min(28, (iw / data.length) * 0.6), step = iw / data.length;
  const ticks = [0, 0.5, 1].map((f) => Math.round(max * f));
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label="일별 검사 결과">
      {ticks.map((v, i) => { const y = pad.t + ih - (v / max) * ih; return <g key={i}><line x1={pad.l} x2={W - pad.r} y1={y} y2={y} stroke="#e4e8ee" /><text x={pad.l - 8} y={y + 4} textAnchor="end" fontSize="11" fill="#8b95a1">{v}</text></g>; })}
      {data.map((d, i) => {
        const x = pad.l + step * i + (step - bw) / 2;
        const hp = (d.passed / max) * ih, hf = ((d.failed + d.error) / max) * ih;
        const show = data.length <= 10 || i % Math.ceil(data.length / 10) === 0;
        return (
          <g key={d.day}>
            <title>{`${d.day} · 성공 ${d.passed} · 실패 ${d.failed} · 수행 불가 ${d.error}`}</title>
            <rect x={x} y={pad.t + ih - hp} width={bw} height={hp} rx="4" fill="#1a63f5" />
            <rect x={x} y={pad.t + ih - hp - hf} width={bw} height={hf} rx="4" fill="#c9d1db" />
            {show && <text x={x + bw / 2} y={height - 8} textAnchor="middle" fontSize="11" fill="#8b95a1">{d.day.slice(5)}</text>}
          </g>
        );
      })}
    </svg>
  );
}

export function Bars({ data, unit = "" }: { data: { label: string; value: number }[]; unit?: string }) {
  if (!data.length) return <div className="py-8 text-center text-sm text-mute">집계할 데이터가 없습니다</div>;
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className="space-y-3">{data.map((d) => (
      <li key={d.label} className="grid grid-cols-[96px_1fr_auto] items-center gap-3 text-[13px]">
        <span className="num text-mute">{d.label}</span>
        <span className="h-2 rounded-full bg-raised"><span className="block h-2 rounded-full bg-accent" style={{ width: `${(d.value / max) * 100}%` }} /></span>
        <span className="num text-right">{d.value.toLocaleString("ko-KR")}{unit}</span>
      </li>))}
    </ul>
  );
}

export function Progress({ value }: { value: number }) {
  return <span className="block h-2 w-full rounded-full bg-raised"><span className="block h-2 rounded-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></span>;
}
