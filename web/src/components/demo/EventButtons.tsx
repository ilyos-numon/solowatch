import { Button } from '../ui/Button';
import { DEMO_EVENTS, type DemoEventKind } from '../../lib/demoApi';

interface Props {
  busy: DemoEventKind | null;
  disabled: boolean;
  /** 마지막으로 넣은 이벤트 — aria-pressed 로 표시 */
  pressed: DemoEventKind | null;
  onInject: (kind: DemoEventKind) => void;
}

export default function EventButtons({ busy, disabled, pressed, onInject }: Props) {
  return (
    <div className="events" role="group" aria-label="이벤트">
      {DEMO_EVENTS.map((e) => (
        <Button
          key={e.kind}
          busy={busy === e.kind}
          disabled={disabled && busy !== e.kind}
          aria-pressed={pressed === e.kind}
          onClick={() => onInject(e.kind)}
          testId={`btn-inject-${e.kind}`}
        >
          {e.label}
        </Button>
      ))}
    </div>
  );
}
