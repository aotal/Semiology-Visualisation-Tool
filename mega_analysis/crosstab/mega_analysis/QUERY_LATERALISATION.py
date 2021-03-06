import logging
import pandas as pd
import numpy as np
from tqdm import tqdm
from colorama import Fore

from .mapping import big_map, pivot_result_to_one_map
from .group_columns import full_id_vars, lateralisation_vars


# main function is QUERY_LATERALISATION


def gifs_lat(gif_lat_file):
    """
    factor function. opens the right/left gif parcellations from excel and extracts the right/left gifs as series/list.
    """
    gifs_right = gif_lat_file.loc[gif_lat_file['R'].notnull(), 'R'].copy()
    gifs_left = gif_lat_file.loc[gif_lat_file['L'].notnull(), 'L'].copy()

    return gifs_right, gifs_left


def summarise_overall_lat_values(row,
                                 side_of_symptoms_signs,
                                 pts_dominant_hemisphere_R_or_L,
                                 Right,
                                 Left):
    """
    Factor function for Q_L. Calculated IL, CL, DomH and NonDomH lateralisations.
    """
    IL_row = row['IL'].sum()
    CL_row = row['CL'].sum()
    DomH_row = row['DomH'].sum()
    NonDomH_row = row['NonDomH'].sum()
    # BL_row = row['BL (Non-lateralising)'].sum()

    # pt input
    if side_of_symptoms_signs == 'R':
        Right += IL_row
        Left += CL_row

    elif side_of_symptoms_signs == 'L':
        Right += CL_row
        Left += IL_row

    if pts_dominant_hemisphere_R_or_L:
        if pts_dominant_hemisphere_R_or_L == 'R':
            Right += DomH_row
            Left += NonDomH_row
        elif pts_dominant_hemisphere_R_or_L == 'L':
            Right += NonDomH_row
            Left += DomH_row
    return Right, Left


def lateralising_but_not_localising(full_row,
                                    side_of_symptoms_signs,
                                    pts_dominant_hemisphere_R_or_L,
                                    lat_only_Right,
                                    lat_only_Left):
    """
    Part 1 of 2
    Keep the lateralising values: map to unilateral gif parcellations.
        instead of SVT v 1.2.0 (Aug 2020) which ignored this data if there was no localising value.

    """
    lat_only_Right, lat_only_Left = summarise_overall_lat_values(full_row,
                                                                 side_of_symptoms_signs,
                                                                 pts_dominant_hemisphere_R_or_L,
                                                                 lat_only_Right,
                                                                 lat_only_Left)

    return lat_only_Right, lat_only_Left


def lateralising_but_not_localising_GIF(
        all_combined_gifs,
        lat_only_Right, lat_only_Left,
        gifs_right, gifs_left):
    """
    Part 2 of 2
    Keep the lateralising values: map to unilateral gif parcellations.
        instead of SVT v 1.2.0 (Aug 2020) which ignored this data if there is no localising value.

    """
    lat_only_df = pd.DataFrame(columns=['Gif Parcellations', 'pt #s'])

    gifs_right_and_left = gifs_right.append(gifs_left, ignore_index=True)
    lat_only_df['Gif Parcellations'] = gifs_right_and_left
    lat_only_df.loc[lat_only_df['Gif Parcellations'].isin(
        gifs_right), 'pt #s'] = lat_only_Right  # broadcast
    lat_only_df.loc[lat_only_df['Gif Parcellations'].isin(
        gifs_left), 'pt #s'] = lat_only_Left  # broadcast
    return lat_only_df


def lat_exceeding_loc_mapped_to_hemisphericGIFs_adjusted_for_locs(
        full_row, lat_vars,
        side_of_symptoms_signs,
        pts_dominant_hemisphere_R_or_L,
        lat_only_Right,
        lat_only_Left,
        isin_left, isin_right):
    """ Factor function.
    Calculates the excess of lat over loc values.
    Then maps these to GIFs as per lat_but_not_loc.
    Then adjusts for the values already used in Q_L for the localisation GIFs
        i.e. keeps proportion of right/left the same and
        the values not more than lateralisation - localisation
    """
    full_row_lat_excess = full_row.copy()
    # remove loc data and keep only lat data:
    full_row_lat_excess = full_row_lat_excess[lat_vars]
    # now deal with lat_exceed_loc excess as we did with lat_but_not_loc (these aren't lat_only or lat_excess yet)
    lat_only_Right, lat_only_Left = lateralising_but_not_localising(full_row_lat_excess,
                                                                    side_of_symptoms_signs,
                                                                    pts_dominant_hemisphere_R_or_L,
                                                                    lat_only_Right,
                                                                    lat_only_Left)
    # now adjust for the already calculated "proportion_lateralising = 1" locs:
    loc_adjust = full_row['Localising'].sum()
    if lat_only_Left == 0:  # exception, also as this is zero, it must be the smaller of the two i.e. isin_left
        L_to_R_ratio = 0
    elif lat_only_Right == 0:  # exception, also as this is zero, it must be the smaller of the two i.e. isin_right
        R_to_L_ratio = 0
    else:  # DEFAULT: neither are zero as lateralising exceeded loc for this function to be called in first place
        R_to_L_ratio = lat_only_Right / lat_only_Left
        L_to_R_ratio = lat_only_Left / lat_only_Right

    if isin_left:  # left gifs are smaller than right and were reduced.
        lat_only_Right = lat_only_Right - loc_adjust
        # left gifs were smaller and so less used from the lateralising, more remain for lat_excess:
        lat_only_Left = lat_only_Left - (loc_adjust * L_to_R_ratio)
        # the above are now lat_excess_Right and Left, remain named lat_only_Right and left for consistency

    elif isin_right:  # invert above
        lat_only_Left = lat_only_Left - loc_adjust
        lat_only_Right = lat_only_Right - (loc_adjust * (R_to_L_ratio))

    return lat_only_Right, lat_only_Left


def QUERY_LATERALISATION(inspect_result, df, one_map, gif_lat_file,
                         side_of_symptoms_signs=None,
                         pts_dominant_hemisphere_R_or_L=None,
                         normalise_lat_to_loc=False,
                         disable_tqdm=True):
    """
    After obtaining inspect_result and clinician's filter, can optionally use this function to determine
    lateralisation e.g. for EpiNav(R) visualisation.

    Run this after QUERY_SEMIOLOGY OR QUERY_INTERSECTION_TERMS

    inspect_result may not have a lateralising column (if all were NaNs)
    goes through row by row

    ---
    > inspect_result is obtained from QUERY_SEMIOLOGY OR QUERY_INTERSECTION_TERMS
    > df as per pivot_result_to_pixel_intensities's df
    > side_of_symptoms_signs: 'R' or 'L' - side of symptoms/signs on limbs
    > pts_dominant_hemisphere_R_or_L: if known from e.g. fMRI language 'R' or 'L'
    >> gifs_not_lat is the same as localising_only
    >> lat_only_Right/Left lateralising only data

    returns:
        all_combined_gifs: similar in structure to output of pivot_result_to_one_map (final step),
                        but in this case, the output column is pt #s rather than pixel intensity.
        num_QL_lat: Lateralising Datapoints relevant to query {semiology_term}.
                    Should be exactly the same as num_query_lat returned by QUERY_SEMIOLOGY.
        num_QL_CL: Datapoints that lateralise contralateral to the semiology query {semiology_term}
        num_QL_IL: Datapoints that lateralise ipsilaterally to the semiology query {semiology_term}
        num_QL_BL: Study reports the datapoint as being Bilateral. Non-informative and not utilised in our analysis/visualisation.
        num_QL_DomH: Semiology query datapoints lateralise to the Dominant Hemisphere
        num_QL_NonDomH: Semiology query datapoints lateralise to the Non-Dominant Hemisphere


    Should then run this again through a similar process as
        pivot_result_to_pixel_intensity to curve fit (MinMaxScaler, QuantileTransformer or Chi2)
    ---

    Alim-Marvasti Aug 2019
    """
    pd.options.mode.chained_assignment = 'raise'
    df = df.copy()

    # ensure there is patient's lateralised signs and check dominant known or not
    if not side_of_symptoms_signs and not pts_dominant_hemisphere_R_or_L:
        # print('Please note you must determine at least one of side_of_symptoms_signs or')
        # print('pts_dominant_hemisphere_R_or_L keyword arguments for lateralised data extraction.')
        return None, None, None, None, None, None, None

    # check there is lateralising value
    try:
        num_QL_lat = inspect_result['Lateralising'].sum()
        if num_QL_lat > 0:
            logging.debug(
                f'\n\nLateralisation based on: {num_QL_lat.sum()} datapoints')
        else:
            num_QL_lat = None
            return None, None, None, None, None, None, None
    except KeyError:
        # logging.debug(
        #     f'No Lateralising values found for this query of the database.')
        num_QL_lat = None
        return None, None, None, None, None, None, None

    lat_vars = [i for i in lateralisation_vars() if i not in ['Lateralising']]

    # check that the lateralising columns isn't null where it shouldn't be i.e. CL/IL/DomH/NonDomH not null:
    # but not 'BL (Non-lateralising)'
    # first ensure other columns all feature in this inspect_result:
    inspect_result2 = inspect_result.copy()
    for col in lat_vars:
        if col not in inspect_result2.columns:
            inspect_result2[col] = np.nan
    # now can check lateralising columns isn't null where it shouldn't be:
    missing_lat = inspect_result2.loc[(inspect_result2['CL'].notnull()) |
                                      (inspect_result2['IL'].notnull()) |
                                      (inspect_result2['DomH'].notnull()) |
                                      (inspect_result2['NonDomH'].notnull()), :].copy()
    missing_lat_null_mask = missing_lat['Lateralising'].isnull()
    if not missing_lat_null_mask.all():
        # logging.debug('\nNo missing Lateralising data points.')
        pass
    else:
        logging.debug(
            'The inspect_result lat col has NaNs/zero where it should not: autofilled')
        df_of_missing_lats = missing_lat.loc[missing_lat_null_mask].copy()
        df.loc[df_of_missing_lats.index, 'Lateralising'] = df_of_missing_lats[[
            'CL', 'IL', 'DomH', 'NonDomH']].sum(axis=1)

    # check columns exist (not removed in preceding notnull steps from other functions):
    for col in lat_vars:
        if col not in inspect_result.columns:
            inspect_result[col] = 0

    # summarise overall lat values
    IL = inspect_result['IL']
    CL = inspect_result['CL']
    DomH = inspect_result['DomH']
    NonDomH = inspect_result['NonDomH']
    BL = inspect_result['BL (Non-lateralising)']

    num_QL_CL = CL.sum()
    num_QL_IL = IL.sum()
    num_QL_BL = BL.sum()
    num_QL_DomH = DomH.sum()
    num_QL_NonDomH = NonDomH.sum()

    logging.debug(f'\n\nOverall Contralateral: {num_QL_CL} datapoints')
    logging.debug(f'Ipsilateral: {num_QL_IL} datapoints')
    logging.debug(
        f'Bilateral/Non-lateralising: {num_QL_BL} datapoints. This is not utilised in our analysis/visualisation.')
    logging.debug(f'Dominant Hemisphere: {num_QL_DomH} datapoints')
    logging.debug(f'Non-Dominant Hemisphere: {num_QL_NonDomH} datapoints')

    # Global initialisation:
    lat_only_Right = 0
    lat_only_Left = 0
    inspect_result_lat = inspect_result.loc[inspect_result['Lateralising'].notnull(
    ), :].copy()  # only those with lat (with or without localising)
    no_rows = inspect_result_lat.shape[0]
    all_combined_gifs = None
    gifs_right, gifs_left = gifs_lat(gif_lat_file)

    # cycle through rows of inspect_result_lat:
    id_cols = [i for i in full_id_vars() if i not in ['Localising']
               ]  # note 'Localising' is in id_cols

    for i in (range(no_rows) if disable_tqdm else tqdm(range(no_rows), desc='QUERY LATERALISTION: main',
                                                       bar_format="{l_bar}%s{bar}%s{r_bar}" % (Fore.BLUE, Fore.RESET))):
        # logging.debug(str(i))
        Right = 0
        Left = 0

        full_row = inspect_result_lat.iloc[[i], :]
        row = full_row.drop(labels=id_cols, axis='columns',
                            inplace=False, errors='ignore')
        row = row.dropna(how='all', axis='columns')
        # row = row.dropna(how='all', axis='rows')

        #
        #
        #
        # some pts/rows will have lateralising but no localising values:
        if (('Localising' not in row.columns) | (full_row['Localising'].sum() == 0)):
            logging.debug(
                '\n\nSome extracted lateralisations have no specific localisation - these are mapped to entire hemispheric GIFs')
            # logging.debug(f'row# = {i}')
            # probably, in future, instead of break we want to compare this row's:
            #       full_row['Lateralising']    to the overall    inspect_result['Lateralising']    and use that proportion
            #  or actually, to count this full_row['Lateralising'] as data for localising, using the lateralised gif parcellations from the sheet called
            #       'Full GIF Map for Review '

            lat_only_Right, lat_only_Left = lateralising_but_not_localising(full_row,
                                                                            side_of_symptoms_signs,
                                                                            pts_dominant_hemisphere_R_or_L,
                                                                            lat_only_Right,
                                                                            lat_only_Left)
            continue
        #
        #
        #
        # otherwise if there is localising value (and lateralising value):
        row_to_one_map = pivot_result_to_one_map(row, one_map, raw_pt_numbers_string='pt #s',
                                                 )
        # ^ row_to_one_map now contains all the lateralising gif parcellations

        # set the scale of influence of lateralisation on the gif parcellations:
        proportion_lateralising = full_row['Lateralising'].sum(
        ) / full_row['Localising'].sum()

        # some rows will have lateralisng exceed localising values:
        #
        #
        #
        if proportion_lateralising > 1:
            proportion_lateralising = 1
            logging.debug(
                '\n\nSome lateralising data exceed localising data, excess are mapped to entire hemispheric GIFs')

            # now deal with lat_exceed_loc excess as we did with lat_but_not_loc
            lat_exceed_loc = True
        else:
            lat_exceed_loc = False

        # check columns exist in this particular row:
        for col in lat_vars:
            if col not in row.columns:
                row[col] = 0
            else:
                continue

        # summarise overall lat values
        Right, Left = summarise_overall_lat_values(row,
                                                   side_of_symptoms_signs,
                                                   pts_dominant_hemisphere_R_or_L,
                                                   Right,
                                                   Left)

        Total = Right+Left
        if Right == Left:
            # no point as this is 50:50 as it already is, so skip
            # before continuing, ensure there is a all_combined_gifs...
            # e.g. for blink there isn't as the first row is 50:50...
            # ... and all future codes fail
            if all_combined_gifs is None:
                all_combined_gifs = row_to_one_map
            elif all_combined_gifs is not None:
                all_combined_gifs = pd.concat(
                    [all_combined_gifs, row_to_one_map], join='outer', sort=False, ignore_index=True)
            continue

        # now should be able to use above to lateralise the localising gif parcellations:
        # if there are 100 localisations in one row, and only 1 IL And 3 CL, it would be too much
        # to say the IL side gets one third of the CL side as number of lat is too low
        # hence normalise by dividing by proportion_lateralising (which is between (0,1])

        # find lowest value of R or L
        lower_postn = np.argmin([Right, Left])
        if lower_postn == 0:
            isin = gifs_right  # reduce right sided intensities/pt #s
            isin_right = True
            isin_left = False
        elif lower_postn == 1:
            isin = gifs_left
            isin_left = True
            isin_right = False

        lower_value = [Right, Left][lower_postn]
        higher_value = [Right, Left]
        higher_value.remove(lower_value)

        ratio = lower_value / Total

        if normalise_lat_to_loc == True:
            # see comments on section above about why we should normalise
            norm_ratio = ratio / proportion_lateralising
            if norm_ratio > 1:
                norm_ratio = 1
                logging.debug(
                    'norm_ratio capped at 1: small proportion of data lateralised')
        elif normalise_lat_to_loc == False:
            norm_ratio = lower_value / higher_value

        # if proportion_lateralising is 1, straightforward: return dataframe of right/left gifs whichever lower
        df_lower_lat_to_be_reduced = row_to_one_map.loc[row_to_one_map['Gif Parcellations'].isin(
            list(isin))].copy()
        # now make these values lower by a proportion = norm_ratio (in this case norm_ratio = ratio as denom is 1)
        reduce_these = df_lower_lat_to_be_reduced.loc[:, 'pt #s'].copy()
        df_lower_lat_to_be_reduced.loc[:, 'pt #s'] = norm_ratio * reduce_these
        # re attribute these corrected reduced lateralised values to the entire row's data:
        row_to_one_map.loc[df_lower_lat_to_be_reduced.index,
                           :] = df_lower_lat_to_be_reduced

        #
        #
        #
        # now deal with lat_exceed_loc excess as we did with lat_but_not_loc
        if lat_exceed_loc:
            lat_only_Right, lat_only_Left = lat_exceeding_loc_mapped_to_hemisphericGIFs_adjusted_for_locs(
                full_row, lat_vars,
                side_of_symptoms_signs,
                pts_dominant_hemisphere_R_or_L,
                lat_only_Right,
                lat_only_Left,
                isin_left=isin_left, isin_right=isin_right,
            )

        #
        #
        #

        # now need to merge/concat these rows-(pivot-result)-to-one-map as the cycle goes through each row:
        if i == 0:
            # can't merge first row
            all_combined_gifs = row_to_one_map
            # logging.debug('end of zeroo')
            continue
        elif i != 0:
            all_combined_gifs = pd.concat(
                [all_combined_gifs, row_to_one_map], join='outer', sort=False, ignore_index=True)
        # logging.debug(f'end of i {i}')

    # Need to recombine the inspect_result_lat (also had loc) used in for loop to give all_combined_gifs
    # with inspect_result that had null lateralising:
    inspect_result_nulllateralising = inspect_result.loc[inspect_result['Lateralising'].isnull(
    ), :].copy()
    # now clean ready to map:
    inspect_result_nulllateralising.drop(
        labels=id_cols, axis='columns', inplace=True, errors='ignore')
    inspect_result_nulllateralising.dropna(
        how='all', axis='columns', inplace=True)
    # now map row by row otherwise you get a "TypeError: only size-1 arrays can be converted to Python scalars":
    nonlat_no_rows = inspect_result_nulllateralising.shape[0]
    if (nonlat_no_rows == 0) | inspect_result_nulllateralising.empty:
        gifs_not_lat = None
    elif nonlat_no_rows != 0:
        for j in (range(nonlat_no_rows) if disable_tqdm else tqdm(range(nonlat_no_rows), desc='QUERY LATERALISATION: non-lateralising data',
                                                                  bar_format="{l_bar}%s{bar}%s{r_bar}" % (Fore.CYAN, Fore.RESET))):
            full_row = inspect_result_nulllateralising.iloc[[j], :]
            row = full_row.drop(labels=id_cols, axis='columns',
                                inplace=False, errors='ignore')
            row = row.dropna(how='all', axis='columns')
            row_nonlat_to_one_map = pivot_result_to_one_map(row,
                                                            one_map, raw_pt_numbers_string='pt #s',
                                                            )
            if j == 0:
                # can't merge first row
                gifs_not_lat = row_nonlat_to_one_map
                # logging.debug(
                #     'j zero gifs_not_lat set to row_nonlat_to_one_map')
                continue
            elif j != 0:
                gifs_not_lat = pd.concat(
                    [gifs_not_lat, row_nonlat_to_one_map], join='outer', sort=False, ignore_index=True)
    # now combine the lateralised+loc and non-lateralised(=only localised):
    # all_combined_gifs may still be None if after running above with some lateralised...
        # ...semiology or dominance, there is no lateralising data.
    if all_combined_gifs is None:
        all_combined_gifs = gifs_not_lat
    elif all_combined_gifs is not None:
        all_combined_gifs = pd.concat(
            [all_combined_gifs, gifs_not_lat], join='outer', sort=False, ignore_index=True)

    # here add the lateralising_but_not_localising data to the all_combined_gifs (or fixed, or fixed2):
    # if all_combined_gifs is None then use the unilteral_gifs
    # if all_combined_Gifs is not None then only add values to the unilateral gifs if they are already in all_combined_gifs
    if (lat_only_Right != 0) | (lat_only_Left != 0):
        # means both lateralising+loc and gifs_not_lat were none. occurs usually in dummy_data only.
        if all_combined_gifs is None:
            lat_only_df = lateralising_but_not_localising_GIF(all_combined_gifs,
                                                              lat_only_Right, lat_only_Left,
                                                              gifs_right, gifs_left)
            all_combined_gifs = lat_only_df.copy()
        else:
            lat_only_df = lateralising_but_not_localising_GIF(all_combined_gifs,
                                                              lat_only_Right, lat_only_Left,
                                                              gifs_right, gifs_left)
            all_combined_gifs = pd.concat([all_combined_gifs, lat_only_df],
                                          join='outer', sort=False, ignore_index=True)
            # all_combined_gifs.append(lat_only_df) # equivalent to above concat.

    # if EpiNav doesn't sum the pixel intensities: (infact even if it does)
    fixed = all_combined_gifs.pivot_table(
        columns='Gif Parcellations', values='pt #s', aggfunc='sum')
    fixed2 = fixed.melt(value_name='pt #s')
    fixed2.insert(0, 'Semiology Term', np.nan)
    # fixed2.loc[0, 'Semiology Term'] = str( list(inspect_result.index.values) )
    all_combined_gifs = fixed2
    all_combined_gifs

    return (all_combined_gifs,
            num_QL_lat, num_QL_CL, num_QL_IL, num_QL_BL, num_QL_DomH, num_QL_NonDomH)
