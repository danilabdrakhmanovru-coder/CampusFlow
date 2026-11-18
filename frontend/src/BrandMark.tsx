export function BrandMark() {
  return <span className="logo-mark" aria-hidden="true">
    <svg viewBox="0 0 24 24" focusable="false">
      {[0,1,2,3,4,5,6,7,8].map(index=><rect key={index} x={2+index%3*7} y={2+Math.floor(index/3)*7}
        width="6" height="6" rx="1.4" className={index===8?'logo-cell-accent':'logo-cell'}/>)}
    </svg>
  </span>
}
