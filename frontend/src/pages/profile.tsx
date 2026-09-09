import { EducationSection } from '@/features/profile/EducationSection'
import { ExperienceSection } from '@/features/profile/ExperienceSection'
import { OverviewSection } from '@/features/profile/OverviewSection'
import { PreferencesSection } from '@/features/profile/PreferencesSection'
import { SkillsSection } from '@/features/profile/SkillsSection'

export function ProfilePage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <OverviewSection />
      <ExperienceSection />
      <EducationSection />
      <SkillsSection />
      <PreferencesSection />
    </div>
  )
}
