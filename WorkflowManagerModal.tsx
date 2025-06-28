import React, { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { WorkflowListItem } from './api'; // Импортируем наш тип
import { Trash2, FilePlus2 } from 'lucide-react';

interface WorkflowManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  workflows: WorkflowListItem[];
  onLoad: (id: string) => void;
  onCreate: (name: string) => Promise<void>;
  onDelete: (id: string) => void;
}

export const WorkflowManagerModal: React.FC<WorkflowManagerModalProps> = ({
  isOpen,
  onClose,
  workflows,
  onLoad,
  onCreate,
  onDelete,
}) => {
  const [newWorkflowName, setNewWorkflowName] = useState('');

  const handleCreate = async () => {
    if (newWorkflowName.trim()) {
      await onCreate(newWorkflowName.trim());
      setNewWorkflowName('');
      // onClose(); // Можно закрыть модалку после создания
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[525px]">
        <DialogHeader>
          <DialogTitle>Управление Workflows</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="flex items-center space-x-2">
            <Input
              placeholder="Имя нового workflow..."
              value={newWorkflowName}
              onChange={(e) => setNewWorkflowName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            />
            <Button onClick={handleCreate} disabled={!newWorkflowName.trim()}>
              <FilePlus2 className="h-4 w-4 mr-2" />
              Создать
            </Button>
          </div>
          <h3 className="text-lg font-medium mt-4">Существующие Workflows</h3>
          <ScrollArea className="h-[300px] w-full rounded-md border p-4">
            {workflows.length > 0 ? (
              workflows.map((wf) => (
                <div key={wf.id} className="flex items-center justify-between mb-2 p-2 rounded-lg hover:bg-accent">
                  <span className="font-medium">{wf.name}</span>
                  <div className="flex items-center space-x-2">
                    <Button variant="outline" size="sm" onClick={() => onLoad(wf.id)}>
                      Загрузить
                    </Button>
                    <Button
                      variant="destructive"
                      size="icon"
                      onClick={() => {
                        if (window.confirm(`Вы уверены, что хотите удалить "${wf.name}"?`)) {
                          onDelete(wf.id);
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground text-center">Нет сохраненных workflows.</p>
            )}
          </ScrollArea>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>Закрыть</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
