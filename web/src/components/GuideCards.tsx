export default function GuideCards() {
  return (
    <aside className="side" data-testid="guide-cards">
      <div className="hs-card">
        <h2>이 앱이 받는 것과 받지 않는 것</h2>
        <div className="bound">
          <div>
            <strong>집 안</strong>수도·냉장고·TV·거실등의 5분 단위 값. 기기 안에서만 평소와 비교합니다.
          </div>
          <div className="wall" aria-hidden="true" />
          <div>
            <strong>가족 앱</strong>알림 문장, 하루 요약, 시간별 사용 있음·없음. 응답과 외출 표시는 집으로 돌아갑니다.
          </div>
        </div>
        <p className="hs-note">응급 자동 신고는 하지 않습니다. 이상인지는 가족이 판단합니다.</p>
      </div>
      <div className="hs-card">
        <h2>알림에 답하면</h2>
        <ol className="flow">
          <li>
            <b>1</b>
            <span>
              <strong>괜찮았음</strong>을 누르면 집의 기기가 그 시간대의 평소 기준을 다시 배웁니다. 한 번에 알림이 사라지지는 않을 수
              있지만 평소와 다른 정도는 줄어듭니다.
            </span>
          </li>
          <li>
            <b>2</b>
            <span>
              <strong>확인 중</strong>과 <strong>실제 이상</strong>은 표시만 바꾸고 학습에는 쓰지 않습니다.
            </span>
          </li>
          <li>
            <b>3</b>
            <span>답은 나중에 바꿀 수 있습니다. 가장 마지막 답이 그 알림의 상태가 됩니다.</span>
          </li>
        </ol>
      </div>
      <div className="hs-card">
        <h2>알림 문장 읽는 법</h2>
        <p className="hs-note">
          알림은 늘 같은 순서로 씁니다. 시간대, 무엇이 달랐는지, 평소와 다르다는 말입니다. 시각은 알림이 온 때가 아니라 그 시간대가
          시작한 때입니다.
        </p>
      </div>
    </aside>
  );
}
