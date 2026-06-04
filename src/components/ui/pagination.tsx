interface PaginationProps {
  page: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  onPage: (page: number) => void;
}

export function Pagination({ page, totalPages, totalItems, pageSize, onPage }: PaginationProps) {
  if (totalPages <= 1) return null;

  const from = (page - 1) * pageSize + 1;
  const to   = Math.min(page * pageSize, totalItems);
  const start = Math.max(1, Math.min(page - 2, totalPages - 4));
  const pages = Array.from({ length: Math.min(5, totalPages) }, (_, i) => start + i);

  return (
    <div className="flex items-center justify-between mt-4 pt-3 border-t">
      <span className="text-xs text-muted-foreground">
        {from}–{to} of {totalItems}
      </span>
      <div className="flex gap-1 items-center">
        <NavBtn onClick={() => onPage(1)}         disabled={page === 1}>«</NavBtn>
        <NavBtn onClick={() => onPage(page - 1)}  disabled={page === 1}>‹</NavBtn>
        {pages.map(p => (
          <button key={p} onClick={() => onPage(p)}
            className={`px-2.5 py-1 text-xs rounded border transition-colors ${
              p === page ? "bg-primarygreen text-white border-primarygreen" : "hover:bg-neutral-50"
            }`}>
            {p}
          </button>
        ))}
        <NavBtn onClick={() => onPage(page + 1)}  disabled={page === totalPages}>›</NavBtn>
        <NavBtn onClick={() => onPage(totalPages)} disabled={page === totalPages}>»</NavBtn>
      </div>
    </div>
  );
}

function NavBtn({ onClick, disabled, children }: { onClick: () => void; disabled: boolean; children: React.ReactNode }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="px-2 py-1 text-xs rounded border disabled:opacity-30 hover:bg-neutral-50">
      {children}
    </button>
  );
}
