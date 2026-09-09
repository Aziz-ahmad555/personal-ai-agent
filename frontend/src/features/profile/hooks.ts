import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  type EducationInput,
  type PreferencesInput,
  type ProfileUpdateInput,
  type SkillVersionInput,
  type WorkExperienceInput,
  profileApi,
} from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

export function useProfile() {
  const token = useToken()
  return useQuery({ queryKey: ['profile'], queryFn: () => profileApi.get(token) })
}

export function useUpdateProfile() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: ProfileUpdateInput) => profileApi.update(token, input),
    onSuccess: (data) => queryClient.setQueryData(['profile'], data),
  })
}

export function useAddLink() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { label: string; url: string }) => profileApi.addLink(token, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['profile'] }),
  })
}

export function useDeleteLink() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => profileApi.deleteLink(token, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['profile'] }),
  })
}

export function useExperience() {
  const token = useToken()
  return useQuery({ queryKey: ['experience'], queryFn: () => profileApi.listExperience(token) })
}

export function useCreateExperience() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: WorkExperienceInput) => profileApi.createExperience(token, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['experience'] }),
  })
}

export function useUpdateExperience() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<WorkExperienceInput> }) =>
      profileApi.updateExperience(token, id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['experience'] }),
  })
}

export function useDeleteExperience() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => profileApi.deleteExperience(token, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['experience'] }),
  })
}

export function useEducation() {
  const token = useToken()
  return useQuery({ queryKey: ['education'], queryFn: () => profileApi.listEducation(token) })
}

export function useCreateEducation() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: EducationInput) => profileApi.createEducation(token, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['education'] }),
  })
}

export function useDeleteEducation() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => profileApi.deleteEducation(token, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['education'] }),
  })
}

export function useSkills() {
  const token = useToken()
  return useQuery({ queryKey: ['skills'], queryFn: () => profileApi.listSkills(token) })
}

export function useCreateSkill() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { name: string; category?: string | null }) => profileApi.createSkill(token, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['skills'] }),
  })
}

export function useDeleteSkill() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => profileApi.deleteSkill(token, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['skills'] }),
  })
}

export function useAddSkillVersion() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ skillId, input }: { skillId: string; input: SkillVersionInput }) =>
      profileApi.addSkillVersion(token, skillId, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['skills'] }),
  })
}

export function usePreferences() {
  const token = useToken()
  return useQuery({ queryKey: ['preferences'], queryFn: () => profileApi.getPreferences(token) })
}

export function useUpdatePreferences() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: PreferencesInput) => profileApi.updatePreferences(token, input),
    onSuccess: (data) => queryClient.setQueryData(['preferences'], data),
  })
}
