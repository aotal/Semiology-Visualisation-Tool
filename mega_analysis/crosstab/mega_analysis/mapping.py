import logging
import pandas as pd
import numpy as np
from .group_columns import full_id_vars, lateralisation_vars


def mapping(map_df_dict):
    """
    Uses Ali and Gloria's brain reported localisation in literature to GIF parcellations,
    using Ali and Gloria's mapping.

    # These are the maps for each lobe
    #     mapping_FL = map_df_dict['GIF FL']
    #     mapping_TL = map_df_dict['GIF TL']
    #     mapping_PL = map_df_dict['GIF PL']
    #     mapping_OL = map_df_dict['GIF OL']
    #     mapping_CING = map_df_dict['GIF CING']
    #     mapping_INSULA = map_df_dict['GIF INSULA']
    #     mapping_HYPOTHALAMUS = map_df_dict['GIF HYPOTHALAMUS'] NB GIF parcellation missing hypothalamic parcellation so using thalamus instead.
    #     mapping_CEREBELLUM = map_df_dict['GIF CEREBELLUM']
    #     mapping_MIXED = map_df_dict['GIF_MIXED']

    Aug 2019/2020 Ali Alim-Marvasti

    """
    map_df_dict = map_df_dict.copy()

    for lobe in map_df_dict.keys():
        map_df_dict[lobe] = map_df_dict[lobe].dropna(axis='rows', how='all')
        map_df_dict[lobe] = map_df_dict[lobe].dropna(axis='columns', how='all')

    return map_df_dict


def big_map(map_df_dict):
    """
    Appends all the localisation-to-gif-mapping-DataFrames into one big DataFrame.
    """
    map_df_dict = mapping(map_df_dict)
    one_map = pd.DataFrame()
    for lobe in map_df_dict.keys():
        one_map = one_map.append(map_df_dict[lobe], sort=False)

    return one_map


def pivot_result_to_one_map(
        pivot_result,
        *one_map,
        raw_pt_numbers_string='pt #s',
        map_df_dict=None,
):
    """
    Run after pivot_result_to_pixel_intensities - unless being called as part of QUERY_LATERALISATION.
    This is the Final Step without lateralisation.

    * for each col in pivot_result, find the mapping col numbers, dropna axis rows.
    * then make new col and add the ~pt numbers and pixel intensity for all i.e. ffill-like using slicing
    * note that if you use pivot_result, all_gifs gives you the map with the pt #s. Instead, if you use
        pivot_result_intensities, all_gifs output returns the same but instead of pt #s, intensities from the previous step.

    Makes a dataframe as it goes along, appending all the mappings.
    """
    if not one_map:
        if map_df_dict is None:
            raise ValueError(
                'If one_map not provided, map_df_dict cannot be None')
        one_map = big_map(map_df_dict)
        # one_map = one_map[0]
    if isinstance(one_map, tuple):
        one_map = one_map[0]

    # checks
    lat_vars = lateralisation_vars()
    id_cols = full_id_vars()
    pivot_result_loc_cols = pivot_result.drop(
        lat_vars + id_cols, axis=1, errors='ignore')
    if (len([col for col in pivot_result_loc_cols if col not in one_map]) > 0):
        raise Exception(len([col for col in pivot_result_loc_cols if col not in one_map]),
                        'localisation column(s) in the pivot_result which cannot be found in one_map',
                        'These columns are: ',
                        str([col for col in pivot_result_loc_cols if col not in one_map])
                        )
    else:
        pass
        # print('No issues: pivot_result compared to one_map and all localisations are ready for analysis.')

    # initialisations
    individual_cols = [col for col in pivot_result if col in one_map]
    all_gifs = pd.DataFrame()

    # populate the return df
    for col in individual_cols:
        col_gifs = one_map[[col]].dropna(axis='rows', how='all')
        # add the ~pts numbers:
        col_gifs.loc[:, raw_pt_numbers_string] = float(
            pivot_result[col].values)
        all_gifs = all_gifs.append(col_gifs, sort=False)

    try:
        # stack the resulting all_gifs (values are in 3rd column)
        # # debug lateralising data (fails for e.g. aphasia):
        # from mega_analysis.semiology import mega_analysis_df
        # debug_df_Ref_with_issue = mega_analysis_df.loc[pivot_result.index, [
        # 'Reference', 'Reported Semiology']]
        all_gifs = all_gifs.melt(id_vars=raw_pt_numbers_string,
                                 var_name='Localisation', value_name='Gif Parcellations')  # df
        all_gifs = all_gifs.dropna(axis='rows', how='any')
    #     all_gifs = all_gifs.stack()  #  gives a series
    except KeyError:
        logging.error(f'\nKeyError. all_gifs={all_gifs}')
        logging.error('EMPTY DATAFRAME? SKIPPED THIS ROW. \
                Multiple causes e.g. missing localising values.\
                    See GitHub issue #168 for full details.')

    # insert a new first col which contains the index value of pivot_result (i.e. the semiology term)
    # this is for Rachel Sparks's requirement:
    all_gifs.insert(0, 'Semiology Term', np.nan)
    all_gifs.loc[0, 'Semiology Term'] = str(list(pivot_result.index.values))

    # reorder the columns:
    all_gifs = all_gifs.reindex(columns=['Semiology Term',
                                         'Localisation',
                                         'Gif Parcellations',
                                         raw_pt_numbers_string])

    # if EpiNav doesn't sum the pixel intensities: (infact even if it does)
    fixed = all_gifs.pivot_table(
        columns='Gif Parcellations', values=raw_pt_numbers_string, aggfunc='sum')
    fixed2 = fixed.melt()
    fixed2.insert(0, 'Semiology Term', np.nan)
    fixed2.loc[0, 'Semiology Term'] = str(list(pivot_result.index.values))
    all_gifs = fixed2

    all_gifs.columns = ['Semiology Term',
                        'Gif Parcellations', raw_pt_numbers_string]

    return all_gifs
