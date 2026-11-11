import FamilyHome from '../components/FamilyHome';
import GuideCards from '../components/GuideCards';

export default function Home() {
  return (
    <div className="hs">
      <div className="fam">
        <FamilyHome />
        <GuideCards />
      </div>
    </div>
  );
}
