import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@databricks/appkit-ui/react';
import { EmptyState } from './StateViews';

export function BenefitsDialog() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="text-[color:var(--masthead-foreground)] hover:bg-white/10 hover:text-white">
          Benefícios
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Benefícios</DialogTitle>
          <DialogDescription>Resumo dos ganhos da jornada de dados de ponta a ponta.</DialogDescription>
        </DialogHeader>
        <EmptyState title="Conteúdo em breve" description="Os benefícios serão publicados quando as demais telas estiverem prontas." />
      </DialogContent>
    </Dialog>
  );
}
