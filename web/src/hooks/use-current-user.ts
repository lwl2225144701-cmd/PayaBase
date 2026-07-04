import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { User } from '@/types';

export function useCurrentUser() {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    async function fetchUser() {
      const cachedUser =
        typeof window !== 'undefined' ? localStorage.getItem('currentUser') : null;
      const cachedRole =
        typeof window !== 'undefined' ? localStorage.getItem('userRole') : null;
      
      if (cachedUser) {
        try {
          setUser(JSON.parse(cachedUser));
        } catch {
          localStorage.removeItem('currentUser');
        }
      } else if (cachedRole) {
        setUser({
          id: '',
          tenant_id: '',
          name: '',
          email: '',
          role: cachedRole,
          is_super_admin: cachedRole === 'admin',
          is_training_admin: cachedRole === 'training_admin',
          can_manage_knowledge_bases: cachedRole === 'admin' || cachedRole === 'training_admin',
        });
      }
      
      try {
        const data = await api.getCurrentUser();
        setUser(data);
        if (typeof window !== 'undefined') {
          localStorage.setItem('userRole', data.role || 'user');
          localStorage.setItem('currentUser', JSON.stringify(data));
        }
      } catch (e) {
        if (!cachedRole && !cachedUser) {
          setError(e as Error);
        }
      } finally {
        setIsLoading(false);
      }
    }
    
    fetchUser();
  }, []);

  const isSuperAdmin = !!user?.is_super_admin || user?.role === 'admin';
  const isTrainingAdmin = !!user?.is_training_admin || user?.role === 'training_admin';
  const canManageKnowledgeBases =
    !!user?.can_manage_knowledge_bases || isSuperAdmin || isTrainingAdmin;

  return {
    user,
    isLoading,
    isAdmin: isSuperAdmin,
    isSuperAdmin,
    isTrainingAdmin,
    canManageKnowledgeBases,
    error,
    refetch: () => window.location.reload(),
  };
}
