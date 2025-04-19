package com.reely.mapper;

import org.apache.ibatis.annotations.Mapper;

import com.reely.dto.MovieDto;

@Mapper
public interface MovieMapper {

    int insertCountryInfo(MovieDto movieDto);
    int insertProductionInfo(MovieDto movieDto);
    
}
