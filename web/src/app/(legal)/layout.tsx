import { SiteFooter } from "@/components/site-footer";

export default function LegalLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="min-h-screen bg-gray-50 px-4 py-10">
      <div className="mx-auto w-full max-w-2xl">
        <article className="rounded-lg border border-gray-200/80 bg-white px-6 py-8 shadow-sm sm:px-8">
          {children}
        </article>
        <SiteFooter />
      </div>
    </div>
  );
}
