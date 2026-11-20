import { createBrowserRouter, Navigate, NavLink, Outlet, RouterProvider } from 'react-router';
import { useState } from 'react';
import { Button, Sheet, SheetContent, SheetHeader, SheetTitle, useIsMobile } from '@databricks/appkit-ui/react';
import { Menu } from 'lucide-react';
import { AuroraLogo } from '@/brand/AuroraLogo';
import { BenefitsDialog } from '@/components/BenefitsDialog';
import { HealthBadge } from '@/components/HealthBadge';
import { EmptyState } from '@/components/StateViews';
import { AftersalesPage } from '@/pages/AftersalesPage';
import { GeniePage } from '@/pages/GeniePage';
import { MarketPage } from '@/pages/MarketPage';
import { SectionPage } from '@/pages/SectionPage';
import { SECTIONS } from '@/sections';

const linkClass = (block: boolean) => ({ isActive }: { isActive: boolean }) =>
  block
    ? `block px-3 py-2 rounded-md text-base font-medium ${isActive ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`
    : `relative flex h-14 items-center px-3 text-[15px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-white ${
        isActive
          ? 'text-white after:absolute after:inset-x-3 after:bottom-0 after:h-[3px] after:bg-accent'
          : 'text-[color:var(--masthead-foreground)] hover:text-white'
      }`;

function NavLinks({ className, block, onClick }: { className?: string; block?: boolean; onClick?: () => void }) {
  return (
    <nav aria-label="Seções" className={className}>
      {SECTIONS.map((s) => (
        <NavLink key={s.path} to={s.path} className={linkClass(!!block)} onClick={onClick}>
          {s.label}
        </NavLink>
      ))}
    </nav>
  );
}

function Layout() {
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-background focus:p-2">
        Ir para o conteúdo
      </a>
      <header className="bg-[color:var(--masthead)] px-4 md:px-6 flex h-14 items-center gap-6">
        <h1 className="m-0">
          <AuroraLogo />
        </h1>
        <NavLinks className="hidden md:flex h-full" />
        <div className="ml-auto flex items-center gap-3">
          <HealthBadge />
          <BenefitsDialog />
          <div className="md:hidden">
            <Sheet open={open && isMobile} onOpenChange={setOpen}>
              <Button variant="ghost" size="icon" className="text-white hover:bg-white/10 hover:text-white" onClick={() => setOpen(true)}>
                <Menu className="h-5 w-5" aria-hidden />
                <span className="sr-only">Abrir navegação</span>
              </Button>
              <SheetContent side="left">
                <SheetHeader>
                  <SheetTitle>Navegação</SheetTitle>
                </SheetHeader>
                <NavLinks className="flex flex-col gap-1" block onClick={() => setOpen(false)} />
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </header>
      <main id="main" className="flex-1 px-4 py-8 md:px-8 md:py-10">
        <Outlet />
      </main>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <Navigate to={SECTIONS[0].path} replace /> },
      ...SECTIONS.map((s) => ({
        path: s.path,
        element:
          s.path === '/mercado' ? (
            <MarketPage title={s.label} description={s.description} />
          ) : s.path === '/pos-venda' ? (
            <AftersalesPage title={s.label} description={s.description} />
          ) : s.path === '/genie' ? (
            <GeniePage title={s.label} description={s.description} />
          ) : (
            <SectionPage title={s.label} description={s.description} />
          ),
      })),
      { path: '*', element: <EmptyState title="Página não encontrada" description="Use o menu para navegar entre as seções." /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
