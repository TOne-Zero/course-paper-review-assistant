import type { Rubric } from './model';
import type { CriteriaStandard, Dimension } from './components/CriteriaEditor';

export function rubricDimensions(rubric: Rubric): Dimension[] {
  return rubric.dimensions.map(dimension => ({ id: dimension.id, name: dimension.name, weight: dimension.max_score,
    detailText: (dimension.checklist?.length ? dimension.checklist : [dimension.description]).join('；'),
    detailScores: dimension.checklist_scores,
  }));
}
export const criteriaStandards = (rubrics: Rubric[]): CriteriaStandard[] => rubrics.map(rubric => ({
  id: rubric.id, name: rubric.name.replace(/（.*?）/g, ''), dimensions: rubricDimensions(rubric),
}));
