package com.reely.mapper;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;

import com.reely.dto.SettingDto;

@Mapper
public interface SettingMapper {
        List<SettingDto> findAll();
}
