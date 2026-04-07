export function SkeletonLine({ className = "" }) {
  return <div className={`bg-gray-800 rounded animate-pulse ${className}`} />;
}

export function SkeletonCard() {
  return (
    <div className="card p-5">
      <SkeletonLine className="h-3 w-1/3 mb-3" />
      <SkeletonLine className="h-8 w-1/2 mb-2" />
      <SkeletonLine className="h-3 w-2/3" />
    </div>
  );
}
