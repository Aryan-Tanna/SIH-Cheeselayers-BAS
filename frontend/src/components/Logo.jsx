import isroLogo from '../assets/isro-logo.svg';

export default function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <img src={isroLogo} alt="ISRO logo" className="w-12 h-12 object-contain shrink-0" />
      <div className="leading-tight">
        <div className="font-black text-gray-900 text-base tracking-tight">Abhay</div>
        <div className="text-[10px] font-semibold text-primary uppercase tracking-widest">अभय</div>
      </div>
      <div className="hidden sm:block h-9 w-px bg-gray-300 mx-1" />
      <div className="hidden sm:block leading-snug text-[10px] font-semibold text-gray-600 uppercase tracking-wide">
        <div>Indian Space Research Organisation (ISRO)</div>
        <div>Department of Space · PS 26174</div>
      </div>
    </div>
  );
}
