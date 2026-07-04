'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useCurrentUser } from '@/hooks/use-current-user';

interface AdminGuardProps {
  children: React.ReactNode;
}

export function AdminGuard({ children }: AdminGuardProps) {
  const router = useRouter();
  const { isLoading, isSuperAdmin } = useCurrentUser();

  useEffect(() => {
    if (!isLoading && !isSuperAdmin) {
      router.push('/chat');
    }
  }, [isLoading, isSuperAdmin, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        加载中...
      </div>
    );
  }

  if (!isSuperAdmin) {
    return null;
  }

  return <>{children}</>;
}

export function KnowledgeAdminGuard({ children }: AdminGuardProps) {
  const router = useRouter();
  const { isLoading, canManageKnowledgeBases } = useCurrentUser();

  useEffect(() => {
    if (!isLoading && !canManageKnowledgeBases) {
      router.push('/chat');
    }
  }, [isLoading, canManageKnowledgeBases, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        加载中...
      </div>
    );
  }

  if (!canManageKnowledgeBases) {
    return null;
  }

  return <>{children}</>;
}
