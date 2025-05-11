package com.reely.mapper;

import org.apache.ibatis.annotations.Mapper;

import com.reely.dto.MovieDto;

@Mapper
public interface MovieMapper {

    Integer insertCountryInfo(MovieDto movieDto);
    Integer insertProductionImgInfo(MovieDto movieDto);
    Integer insertProductionInfo(MovieDto movieDto);
    Integer insertFileInfo(MovieDto movieDto);
    Integer insertMovieCast(MovieDto movieDto);
    void insertCastInfo(MovieDto movieDto);
    void insertCastMovieInfo(MovieDto movieDto);
    void insertCrewInfo(MovieDto movieDto);
    void insertMovieCrew(MovieDto movieDto);
    void insertCrewMovieInfo(MovieDto movieDto);
    Integer getMovieId();
    Integer getProductionId();
    Integer getCrewId();
    Integer getCastId();
    Integer getFileId();
    Integer getSoundTrackId();
    Integer insertSoundtrackInfo(MovieDto movieDto);
    Integer insertSoundtrackImg(MovieDto movieDto);
    Integer getAlbumId();
}
