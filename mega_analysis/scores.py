from pathlib import Path
from typing import Optional

import yaml
import numpy as np
import pandas as pd

# needed for querying dataframe localisations, Transforming and mapping to EpiNav gif parcellations
from mega_analysis.crosstab.mega_analysis.MEGA_ANALYSIS import MEGA_ANALYSIS
from mega_analysis.crosstab.mega_analysis.QUERY_SEMIOLOGY import QUERY_SEMIOLOGY
from mega_analysis.crosstab.mega_analysis.QUERY_INTERSECTION_TERMS import QUERY_INTERSECTION_TERMS
from mega_analysis.crosstab.mega_analysis.melt_then_pivot_query import *
from mega_analysis.crosstab.mega_analysis.pivot_result_to_pixel_intensities import *

# needed to collate lateralisation data
from mega_analysis.crosstab.mega_analysis.QUERY_LATERALISATION import QUERY_LATERALISATION
from mega_analysis.crosstab.mega_analysis.lateralised_intensities import lateralisation_to_pixel_intensities
from mega_analysis.crosstab.mega_analysis.pivot_result_to_pixel_intensities import *

# mapping to gif
from mega_analysis.crosstab.mega_analysis.mapping import mapping, big_map, pivot_result_to_one_map


# Define paths
repo_dir = Path(__file__).parent.parent
resources_dir = repo_dir / 'resources'
excel_path = resources_dir / 'syst_review_single_table.xlsx'
semiology_dict_path = resources_dir / 'semiology_dictionary.yaml'


# Read Excel file only three times at initialisation
df, _, _ = MEGA_ANALYSIS(excel_data=excel_path)
map_df_dict = pd.read_excel(
    excel_path,
    header=1,
    sheet_name=['GIF TL', 'GIF FL', 'GIF PL', 'GIF OL', 'GIF CING', 'GIF INSULA', 'GIF CEREBELLUM']
)
gif_lat_file = pd.read_excel(
    excel_path,
    header=0,
    sheet_name='Full GIF Map for Review '
)

def recursive_items(dictionary):
    """https://stackoverflow.com/a/39234154/3956024"""
    for key, value in dictionary.items():
        if type(value) is dict:
            yield from recursive_items(value)
        else:
            yield key


def get_all_semiology_terms():
    with open(semiology_dict_path) as f:
        dictionary = yaml.load(f, Loader=yaml.FullLoader)
    return sorted(recursive_items(dictionary))

# Read YAML
all_semiology_terms = get_all_semiology_terms()

# Define constants
LEFT = 'L'
RIGHT = 'R'


class Semiology:
    def __init__(
            self,
            term: str,
            left: bool = False,
            right: bool = False,
            neutral: bool = False,
            seizure_freedom: bool = True,
            concordance: bool = True,
            seeg_es: bool = True,
            et_topology_ez: bool = True,
            ):
        self.term = term
        self.left = left
        self.right = right
        self.neutral = neutral
        self.seizure_freedom = seizure_freedom
        self.concordance = concordance
        self.seeg_es = seeg_es
        self.et_topology_ez = et_topology_ez

    def query_semiology(self):
        if self.term in all_semiology_terms:
            path = semiology_dict_path
        else:
            path = None
        inspect_result = QUERY_SEMIOLOGY(
            df,
            semiology_term=self.term,
            semiology_dict_path=path,
        )
        return inspect_result

    def get_symptoms_side(self):
        if self.left:
            return LEFT
        elif self.right:
            return RIGHT
        else:
            raise ValueError('Choose left or right symptoms side')

    def get_dominant_hemisphere(self):
        return LEFT  # TODO: check with Ali & Gloria

    def query_lateralisation(self):
        query_semiology_result = self.query_semiology()
        all_combined_gifs = QUERY_LATERALISATION(
            query_semiology_result,
            df,
            map_df_dict,
            gif_lat_file,
            side_of_symptoms_signs=self.get_symptoms_side(),
            pts_dominant_hemisphere_R_or_L=self.get_dominant_hemisphere(),
        )
        return all_combined_gifs

    def get_num_patients_dict(self):
        query_lateralisation_result = self.query_lateralisation()
        array = np.array(query_lateralisation_result)
        _, labels, patients = array.T
        num_patients_dict = {
            int(label): float(num_patients)
            for (label, num_patients)
            in zip(labels, patients)
        }
        return num_patients_dict


def get_scores(
        semiology_term='Head version',
        symptoms_side='R',
        dominant_hemisphere='L',
        output_path=None,
        method='min_max',
        ):
    """
    Methods can be:
    Ali says:
    # I reconmend minmaxscaler.
    method = 'non-linear'
    method = 'min_max'
    method = 'linear'
    method = 'chi2-dist'
    """

    # # LATERALISATION initilisation
    inspect_result = QUERY_SEMIOLOGY(
        df,
        semiology_term=semiology_term,
        semiology_dict_path=semiology_dict_path,
    )

    # # 2.3 QUERY_LATERALISATION
    all_combined_gifs = QUERY_LATERALISATION(
        inspect_result,
        df,
        map_df_dict,
        gif_lat_file,
        side_of_symptoms_signs=symptoms_side,
        pts_dominant_hemisphere_R_or_L=dominant_hemisphere,
    )

    scale_factor = 15
    quantiles = 100
    if method in ('non-linear', 'nonlinear'):
        raw_pt_numbers_string = 'normal QuantileTransformer'
    else:
        raw_pt_numbers_string = str(method)
    intensity_label = 'Lateralised Intensity. '+str(raw_pt_numbers_string)+'. '+'quantiles: '+str(quantiles)+'. '+'scale: '+str(scale_factor)
    all_lateralised_gifs = lateralisation_to_pixel_intensities(
        all_combined_gifs,
        df,
        semiology_term,
        quantiles,
        method=method,
        scale_factor=scale_factor,
        intensity_label=intensity_label,
        use_semiology_dictionary=True,
    )

    array = np.array(all_lateralised_gifs)
    labels = array[:, 1].astype(np.uint16)
    scores = array[:, 3].astype(np.float32)
    scores_dict = {int(label): float(score) for (label, score) in zip(labels, scores)}

    if output_path is not None:
        df_scores = pd.DataFrame(scores_dict.items(), columns=['Label', 'Score'])
        df_scores.to_csv(output_path, index=False)

    return scores_dict


def get_scores_dict(
        semiology_term='Aphasia',
        symptoms_side='R',
        dominant_hemisphere='L',
        output_path=None,
        catch_errors=True,
        ):
    try:
        scores_dict = get_scores(
            semiology_term,
            symptoms_side,
            dominant_hemisphere,
            output_path=output_path,
        )
    except Exception as e:
        print(f'Scores dictionary for semiology term {semiology_term} not retrieved:')
        print(e)
        scores_dict = None
        if not catch_errors:
            raise
    return scores_dict



if __name__ == "__main__":
    semiology = Semiology('Aphasia', left=True)
    semiology.get_num_patients_dict()
