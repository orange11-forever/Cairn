export function Odometer({ value }: { value: number }) {
  const digits = String(value).split("");
  return (
    <span className="odometer">
      <span className="visually-hidden">{value}</span>
      <span aria-hidden="true" className="odometer-digits mono">
        {digits.map((digit, index) => (
          <span className="odometer-digit" data-digit={digit} key={digits.length - index}>
            <span className="odometer-reel" />
          </span>
        ))}
      </span>
    </span>
  );
}
